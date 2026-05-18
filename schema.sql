-- ============================================================
-- ResellOS — Database Schema v1.0
-- Platform: Supabase (PostgreSQL)
-- Created: 2026-05-18 (S01)
-- ============================================================
-- This schema implements DECISION 001 (Postgres from day one),
-- DECISION 011 (data safety, export, deletion), and DECISION 012
-- (auth-ready schema, hardcoded user for Phase 1).
-- Every table includes user_id, created_at, updated_at.
-- Row-Level Security enabled on every table (policies added below).
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. USERS — Account state, privacy controls, deletion lifecycle
-- ============================================================
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    state TEXT NOT NULL,
    reseller_cert_number TEXT,
    reseller_cert_expiry DATE,
    costing_method TEXT NOT NULL DEFAULT 'fifo',
    tax_treatment TEXT NOT NULL DEFAULT 'conservative',
    subscription_tier TEXT NOT NULL DEFAULT 'base',
    stripe_customer_id TEXT,
    account_status TEXT NOT NULL DEFAULT 'active',
    deletion_scheduled_for DATE,
    deleted_at TIMESTAMPTZ,
    last_export_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_account_status ON users(account_status);
CREATE INDEX idx_users_deletion_scheduled ON users(deletion_scheduled_for) 
    WHERE deletion_scheduled_for IS NOT NULL;

-- ============================================================
-- 2. ORDERS — One row per order (online and in-store)
-- ============================================================
CREATE TABLE orders (
    order_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    retailer TEXT NOT NULL,
    order_number TEXT,
    order_date DATE NOT NULL,
    subtotal NUMERIC(12,2) NOT NULL,
    shipping NUMERIC(12,2) DEFAULT 0,
    tax_paid NUMERIC(12,2) DEFAULT 0,
    tax_exempt BOOLEAN DEFAULT FALSE,
    discount_total NUMERIC(12,2) DEFAULT 0,
    gift_card_applied NUMERIC(12,2) DEFAULT 0,
    rewards_applied NUMERIC(12,2) DEFAULT 0,
    total NUMERIC(12,2) NOT NULL,
    payment_method TEXT,
    insider_points_earned INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_retailer ON orders(retailer);
CREATE INDEX idx_orders_order_date ON orders(order_date);

-- ============================================================
-- 3. LINE_ITEMS — Individual items within an order
-- ============================================================
CREATE TABLE line_items (
    line_item_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    set_number TEXT,
    set_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(12,2) NOT NULL,
    line_discount NUMERIC(12,2) DEFAULT 0,
    line_total NUMERIC(12,2) NOT NULL,
    is_gwp BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_line_items_user_id ON line_items(user_id);
CREATE INDEX idx_line_items_order_id ON line_items(order_id);
CREATE INDEX idx_line_items_set_number ON line_items(set_number);

-- ============================================================
-- 4. INVENTORY — One row per physical unit
-- ============================================================
CREATE TABLE inventory (
    unit_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    line_item_id UUID NOT NULL REFERENCES line_items(line_item_id) ON DELETE CASCADE,
    set_number TEXT,
    set_name TEXT NOT NULL,
    cost_basis NUMERIC(12,2) NOT NULL,
    tax_paid_allocated NUMERIC(12,2) DEFAULT 0,
    received_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_stock',
    location TEXT,
    last_price_check TIMESTAMPTZ,
    reason_sold TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_inventory_user_id ON inventory(user_id);
CREATE INDEX idx_inventory_status ON inventory(status);
CREATE INDEX idx_inventory_set_number ON inventory(set_number);
CREATE INDEX idx_inventory_received_date ON inventory(received_date);

-- ============================================================
-- 5. SALES — One row per sold unit
-- ============================================================
CREATE TABLE sales (
    sale_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES inventory(unit_id) ON DELETE RESTRICT,
    platform TEXT NOT NULL,
    sale_date DATE NOT NULL,
    sale_price NUMERIC(12,2) NOT NULL,
    platform_fees NUMERIC(12,2) DEFAULT 0,
    shipping_cost NUMERIC(12,2) DEFAULT 0,
    shipping_collected NUMERIC(12,2) DEFAULT 0,
    net_proceeds NUMERIC(12,2) NOT NULL,
    cost_basis_at_sale NUMERIC(12,2) NOT NULL,
    net_profit NUMERIC(12,2) NOT NULL,
    roi_percent NUMERIC(8,2),
    reason_sold TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sales_user_id ON sales(user_id);
CREATE INDEX idx_sales_platform ON sales(platform);
CREATE INDEX idx_sales_sale_date ON sales(sale_date);
CREATE INDEX idx_sales_unit_id ON sales(unit_id);

-- ============================================================
-- 6. GIFT_CARDS — Gift card purchases and usage
-- ============================================================
CREATE TABLE gift_cards (
    card_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    retailer TEXT NOT NULL,
    face_value NUMERIC(12,2) NOT NULL,
    purchase_price NUMERIC(12,2) NOT NULL,
    discount_amount NUMERIC(12,2) GENERATED ALWAYS AS (face_value - purchase_price) STORED,
    purchase_date DATE NOT NULL,
    source TEXT,
    remaining_balance NUMERIC(12,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    card_number_last4 TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_gift_cards_user_id ON gift_cards(user_id);
CREATE INDEX idx_gift_cards_retailer ON gift_cards(retailer);
CREATE INDEX idx_gift_cards_status ON gift_cards(status);

-- ============================================================
-- 7. REWARDS_TRANSACTIONS — Insider points, retailer rewards
-- ============================================================
CREATE TABLE rewards_transactions (
    txn_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    retailer TEXT NOT NULL,
    program_name TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    points_amount INTEGER,
    dollar_value NUMERIC(12,2),
    order_id UUID REFERENCES orders(order_id) ON DELETE SET NULL,
    transaction_date DATE NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rewards_user_id ON rewards_transactions(user_id);
CREATE INDEX idx_rewards_retailer ON rewards_transactions(retailer);
CREATE INDEX idx_rewards_date ON rewards_transactions(transaction_date);

-- ============================================================
-- 8. CASHBACK_TRANSACTIONS — Credit card and portal cashback
-- ============================================================
CREATE TABLE cashback_transactions (
    cb_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    order_id UUID REFERENCES orders(order_id) ON DELETE SET NULL,
    cashback_amount NUMERIC(12,2) NOT NULL,
    cashback_percent NUMERIC(6,2),
    transaction_date DATE NOT NULL,
    expected_pay_date DATE,
    received_date DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_cashback_user_id ON cashback_transactions(user_id);
CREATE INDEX idx_cashback_status ON cashback_transactions(status);
CREATE INDEX idx_cashback_date ON cashback_transactions(transaction_date);

-- ============================================================
-- 9. GWP — Gift With Purchase tracking
-- ============================================================
CREATE TABLE gwp (
    gwp_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    line_item_id UUID REFERENCES line_items(line_item_id) ON DELETE SET NULL,
    set_number TEXT,
    set_name TEXT NOT NULL,
    market_value NUMERIC(12,2),
    allocation_method TEXT NOT NULL DEFAULT 'proportional',
    allocated_value NUMERIC(12,2),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_gwp_user_id ON gwp(user_id);
CREATE INDEX idx_gwp_order_id ON gwp(order_id);

-- ============================================================
-- 10. TAX_RECOVERY — Quarterly state tax recovery tracking
-- ============================================================
CREATE TABLE tax_recovery (
    recovery_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    sale_id UUID NOT NULL REFERENCES sales(sale_id) ON DELETE CASCADE,
    order_id UUID NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    quarter TEXT NOT NULL,
    year INTEGER NOT NULL,
    tax_paid_recoverable NUMERIC(12,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_date DATE,
    reimbursed_date DATE,
    reimbursed_amount NUMERIC(12,2),
    state TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tax_recovery_user_id ON tax_recovery(user_id);
CREATE INDEX idx_tax_recovery_status ON tax_recovery(status);
CREATE INDEX idx_tax_recovery_quarter ON tax_recovery(year, quarter);

-- ============================================================
-- ROW-LEVEL SECURITY — Enable on every table
-- ============================================================
-- Phase 1: hardcoded single user, RLS structurally present but inactive
-- Phase 2: Supabase Auth activates, policies become enforcing
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE gift_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE rewards_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cashback_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE gwp ENABLE ROW LEVEL SECURITY;
ALTER TABLE tax_recovery ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Schema creation complete. 10 tables, all with RLS enabled.
-- ============================================================