"""Integración con la API PinPad de Clip para cobro automático con terminal.
Referencia: https://developer.clip.mx/reference/introducci%C3%B3n-a-la-api-de-pinpad
Ningún otro módulo debe llamar a la API de Clip directamente — todo pasa por esta clase.
"""
import base64
import json
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ClipPayment, ClipTerminal, ClipPaymentStatus, Sale, User


class ClipServiceError(Exception):
    """Error de comunicación o de negocio al hablar con la API de Clip."""


class PaymentTerminalService(ABC):
    """Interfaz que cualquier proveedor de terminal (Clip, Mercado Pago, ...)
    debe implementar, para que routers/clip.py no dependa de un proveedor concreto."""

    @abstractmethod
    def create_payment(self, **kwargs) -> ClipPayment: ...

    @abstractmethod
    def get_payment(self, pinpad_request_id: str) -> dict: ...

    @abstractmethod
    def cancel_payment(self, payment: ClipPayment) -> ClipPayment: ...

    @abstractmethod
    def cancel_payment_by_terminal(self, terminal: ClipTerminal) -> dict: ...

    @abstractmethod
    def sync_payment(self, payment_id: int) -> ClipPayment: ...


# Ejemplo de mapeo dado en la especificación — Clip no documenta de forma
# consistente todos los valores posibles, así que se cubren los alias conocidos
# y cualquier valor desconocido cae en PENDING (nunca se asume éxito por default).
STATUS_MAPPING = {
    "approved":   ClipPaymentStatus.APPROVED.value,
    "paid":       ClipPaymentStatus.APPROVED.value,
    "completed":  ClipPaymentStatus.APPROVED.value,
    "authorized": ClipPaymentStatus.APPROVED.value,
    "pending":    ClipPaymentStatus.PENDING.value,
    "cancelled":  ClipPaymentStatus.CANCELLED.value,
    "canceled":   ClipPaymentStatus.CANCELLED.value,
    "rejected":   ClipPaymentStatus.DECLINED.value,
    "declined":   ClipPaymentStatus.DECLINED.value,
}


class ClipPinpadService(PaymentTerminalService):
    def __init__(self, db: Session):
        self.db = db
        self._auth_header = self._build_auth_header()

    def _build_auth_header(self) -> str:
        token = base64.b64encode(
            f"{settings.CLIP_API_KEY}:{settings.CLIP_API_SECRET}".encode()
        ).decode()
        return f"Basic {token}"

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def validate_terminal(self, clip_terminal_id: int) -> ClipTerminal:
        terminal = (
            self.db.query(ClipTerminal)
            .filter(ClipTerminal.id == clip_terminal_id, ClipTerminal.is_active == True)
            .first()
        )
        if not terminal:
            raise ClipServiceError("La terminal Clip indicada no existe o está inactiva")
        return terminal

    def map_status(self, clip_status: str) -> str:
        return STATUS_MAPPING.get((clip_status or "").lower(), ClipPaymentStatus.PENDING.value)

    def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        terminal: ClipTerminal,
        tip_amount: Decimal,
        cashier_id: int,
        session_id: Optional[int],
        sale_payload: dict,
        webhook_url: Optional[str] = None,
    ) -> ClipPayment:
        payload = {
            "amount": float(amount),
            "reference": reference,
            "serial_number_pos": terminal.serial_number,
            "tip_amount": float(tip_amount or 0),
            "preferences": {
                "is_auto_return_enabled": True,
                "is_tip_enabled": bool(tip_amount),
                "is_msi_enabled": False,
                "is_mci_enabled": False,
                "is_dcc_enabled": False,
                "is_retry_enabled": True,
                "is_share_enabled": False,
                "is_auto_print_receipt_enabled": False,
                "is_split_payment_enabled": False,
            },
        }
        if webhook_url:
            payload["webhook_url"] = webhook_url

        payment = ClipPayment(
            reference=reference,
            clip_terminal_id=terminal.id,
            cashier_id=cashier_id,
            session_id=session_id,
            amount=amount,
            tip_amount=tip_amount or Decimal("0"),
            status=ClipPaymentStatus.PENDING.value,
            sale_payload=json.dumps(sale_payload, default=str),
        )
        self.db.add(payment)
        self.db.flush()  # obtiene payment.id antes de la llamada externa

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{settings.CLIP_API_BASE_URL}/payment", json=payload, headers=self._headers()
                )
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            payment.status = ClipPaymentStatus.ERROR.value
            payment.error_message = f"Error al conectar con Clip: {exc}"
            self.db.commit()
            raise ClipServiceError(payment.error_message) from exc

        payment.pinpad_request_id = body.get("pinpad_request_id")
        payment.raw_response = json.dumps(body, default=str)
        if not payment.pinpad_request_id:
            payment.status = ClipPaymentStatus.ERROR.value
            payment.error_message = "Clip no devolvió un pinpad_request_id"
        self.db.commit()
        self.db.refresh(payment)
        return payment

    def get_payment(self, pinpad_request_id: str) -> dict:
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    f"{settings.CLIP_API_BASE_URL}/payment",
                    params={"pinpadRequestId": pinpad_request_id},
                    headers=self._headers({"Pinpad-Include-Detail": "true"}),
                )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise ClipServiceError(f"Error al consultar el pago en Clip: {exc}") from exc

    def sync_payment(self, payment_id: int) -> Optional[ClipPayment]:
        """Regla de negocio explícita: NUNCA marcar un pago como aprobado sin
        haber consultado GET /payment. Se llama desde el polling del frontend,
        el webhook, y la tarea periódica de reconciliación — todos convergen aquí."""
        payment = self.db.query(ClipPayment).filter(ClipPayment.id == payment_id).first()
        if not payment or payment.status != ClipPaymentStatus.PENDING.value:
            return payment
        if not payment.pinpad_request_id:
            return payment  # aún no hay respuesta de creación

        body = self.get_payment(payment.pinpad_request_id)
        payment.raw_response = json.dumps(body, default=str)
        payment.last_synced_at = datetime.utcnow()

        detail = ((body.get("detail") or {}).get("results") or [{}])[0]
        new_status = self.map_status(body.get("status") or detail.get("status"))

        payment.amount_paid = body.get("amount_paid") or detail.get("paid_amount")
        payment.transaction_id = detail.get("transaction_id") or detail.get("id")
        payment.merchant_id = detail.get("merchant_id")
        payment.entry_mode = detail.get("entry_mode")
        card = (detail.get("payment_method") or {}).get("card") or {}
        payment.card_brand = detail.get("payment_method", {}).get("type") or payment.card_brand
        payment.last4 = card.get("last_digits") or payment.last4
        payment.issuer = card.get("issuer") or payment.issuer
        if detail.get("approved_at"):
            payment.approved_at = datetime.utcnow()

        payment.status = new_status
        if new_status == ClipPaymentStatus.APPROVED.value and not payment.sale_id:
            try:
                self._create_sale_for_payment(payment)
            except Exception as exc:
                # El cobro en Clip SÍ se aprobó (dinero real capturado) aunque la
                # venta interna no pudo crearse (ej. el stock cambió entre el
                # inicio del cobro y la aprobación) — se conserva el estado
                # approved + el detalle del error para reconciliación manual;
                # nunca se pierde el rastro de un cobro ya realizado.
                payment.error_message = f"Pago aprobado en Clip pero falló creación de venta: {getattr(exc, 'detail', exc)}"

        self.db.commit()
        self.db.refresh(payment)
        return payment

    def cancel_payment(self, payment: ClipPayment) -> ClipPayment:
        if not payment.pinpad_request_id:
            payment.status = ClipPaymentStatus.CANCELLED.value
            self.db.commit()
            return payment
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.delete(
                    f"{settings.CLIP_API_BASE_URL}/payment/{payment.pinpad_request_id}",
                    headers=self._headers(),
                )
            if resp.status_code == 404:
                raise ClipServiceError(
                    "La terminal ya tomó el cobro; no se puede cancelar desde el POS. "
                    "Cancélalo directamente en la terminal."
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClipServiceError(f"Error al cancelar en Clip: {exc}") from exc
        payment.status = ClipPaymentStatus.CANCELLED.value
        self.db.commit()
        self.db.refresh(payment)
        return payment

    def cancel_payment_by_terminal(self, terminal: ClipTerminal) -> dict:
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.delete(
                    f"{settings.CLIP_API_BASE_URL}/payment/serial-number/{terminal.serial_number}",
                    headers=self._headers(),
                )
            if resp.status_code == 400:
                raise ClipServiceError("Hay un pago que la terminal ya tomó y no se puede cancelar por API")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise ClipServiceError(f"Error al cancelar en la terminal: {exc}") from exc

    def process_webhook(self, payload: dict) -> None:
        """Punto de entrada del webhook de Clip. El formato exacto del payload
        varía entre casos documentados por Clip — nunca se confía en su
        contenido como fuente de verdad, solo se usa para ubicar cuál
        ClipPayment pendiente re-sincronizar; sync_payment siempre reconfirma
        con GET /payment antes de marcar nada como aprobado."""
        item = payload.get("item") or {}
        candidate = (
            payload.get("pinpad_request_id")
            or payload.get("reference")
            or payload.get("merch_inv_id")
            or item.get("payment_request_code")
            or item.get("transaction_id")
        )

        pending_q = self.db.query(ClipPayment).filter(
            ClipPayment.status == ClipPaymentStatus.PENDING.value
        )
        matched = None
        if candidate:
            matched = pending_q.filter(
                or_(
                    ClipPayment.pinpad_request_id == candidate,
                    ClipPayment.reference == candidate,
                    ClipPayment.transaction_id == candidate,
                )
            ).first()

        ids = [matched.id] if matched else [p.id for p in pending_q.with_entities(ClipPayment.id).all()]
        for pid in ids:
            try:
                self.sync_payment(pid)
            except Exception as exc:
                print(f"[clip webhook] error sincronizando pago {pid}: {exc}")

    def _create_sale_for_payment(self, payment: ClipPayment) -> Sale:
        from ..routers.sales import _create_sale_internal
        from ..schemas import SaleCreate

        cashier = self.db.query(User).filter(User.id == payment.cashier_id).first()
        if not cashier:
            raise ClipServiceError(f"Cajero {payment.cashier_id} no encontrado; no se puede crear la venta")

        payload = json.loads(payment.sale_payload) if payment.sale_payload else {}
        sale_data = SaleCreate(**payload)
        sale = _create_sale_internal(self.db, sale_data, cashier)
        payment.sale_id = sale.id
        return sale
