import { pgTable, serial, varchar, text, timestamp, boolean, integer, decimal, uuid } from "pg";

// ==================== USER MANAGEMENT ====================

export const users = pgTable("users", {
  id: uuid("id").defaultGenUuid().primaryKey(),
  email: varchar("email", { length: 255 }).notNull().unique(),
  password_hash: varchar("password_hash", { length: 255 }).notNull(),
  first_name: varchar("first_name", { length: 100 }),
  last_name: varchar("last_name", { length: 100 }),
  phone: varchar("phone", { length: 20 }),
  role: varchar("role", { length: 50 }).notNull().default("user"), // user, admin, auditor
  is_active: boolean("is_active").notNull().default(true),
  last_login_at: timestamp("last_login_at"),
  created_at: timestamp("created_at").defaultNow(),
  updated_at: timestamp("updated_at").defaultNow(),
});

export const tenant_users = pgTable("tenant_users", {
  id: serial("id").primaryKey(),
  user_id: uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  tenant_id: uuid("tenant_id").notNull().references(() => tenants.id, { onDelete: "cascade" }),
  role: varchar("role", { length: 50 }).notNull().default("member"), // member, admin, manager
  permissions: text("permissions"), // JSONB array of permission strings
  assigned_by: uuid("assigned_by").references(() => users.id),
  created_at: timestamp("created_at").defaultNow(),
});

// ==================== TENANT MANAGEMENT ====================

export const tenants = pgTable("tenants", {
  id: uuid("id").defaultGenUuid().primaryKey(),
  name: varchar("name", { length: 255 }).notNull(),
  display_name: varchar("display_name", { length: 255 }),
  industry: varchar("industry", { length: 100 }), // agriculture, fintech, logistics
  plan_type: varchar("plan_type", { length: 50 }).notNull().default("free"), // free, starter, professional, enterprise
  status: varchar("status", { length: 20 }).notNull().default("active"), // active, suspended, cancelled
  subscription_status: varchar("subscription_status", { length: 50 }), // active, expired, past_due
  stripe_customer_id: varchar("stripe_customer_id", { length: 255 }),
  created_at: timestamp("created_at").defaultNow(),
  updated_at: timestamp("updated_at").defaultNow(),
});

export const tenant_settings = pgTable("tenant_settings", {
  id: serial("id").primaryKey(),
  tenant_id: uuid("tenant_id").notNull().unique().references(() => tenants.id, { onDelete: "cascade" }),
  company_name: varchar("company_name", { length: 255 }),
  company_address: text("company_address"),
  company_email: varchar("company_email", { length: 255 }),
  support_email: varchar("support_email", { length: 255 }),
  logo_url: varchar("logo_url", { length: 1000 }),
  theme_color: varchar("theme_color", { length: 7 }),
  timezone: varchar("timezone", { length: 50 }).default("UTC"),
  currency: varchar("currency", { length: 3 }).default("USD"),
  language: varchar("language", { length: 10 }).default("en"),
  created_at: timestamp("created_at").defaultNow(),
});