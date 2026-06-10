-- ──────────────────────────────────────────────────────────────────────────
-- POS System – Script de inicialización de MySQL
-- Este archivo es ejecutado automáticamente por Docker al crear el contenedor
-- Para instalación manual: mysql -u pos_user -p pos_db < setup.sql
-- ──────────────────────────────────────────────────────────────────────────

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Crear base de datos si no existe (para instalación manual)
CREATE DATABASE IF NOT EXISTS pos_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE pos_db;

-- ── Las tablas son creadas automáticamente por SQLAlchemy al iniciar el
--    backend (Base.metadata.create_all). Este script agrega datos semilla
--    adicionales opcionales. ─────────────────────────────────────────────────

-- Registros de caja por defecto (se insertan si no existen)
INSERT IGNORE INTO cash_registers (id, name, location, is_active, created_at)
VALUES
  (1, 'Caja Principal', 'Área de ventas 1', 1, NOW()),
  (2, 'Caja 2',         'Área de ventas 2', 1, NOW());

-- Categorías de ejemplo
INSERT IGNORE INTO categories (id, name, description, color, is_active, created_at)
VALUES
  (1, 'Alimentos',        'Productos alimenticios',           '#4CAF50', 1, NOW()),
  (2, 'Bebidas',          'Refrescos, agua y bebidas',        '#2196F3', 1, NOW()),
  (3, 'Limpieza',         'Productos de limpieza del hogar',  '#9C27B0', 1, NOW()),
  (4, 'Higiene personal', 'Cuidado personal',                 '#FF9800', 1, NOW()),
  (5, 'Electrónicos',     'Accesorios y electrónicos',        '#F44336', 1, NOW()),
  (6, 'General',          'Artículos generales',              '#607D8B', 1, NOW());

SET FOREIGN_KEY_CHECKS = 1;
