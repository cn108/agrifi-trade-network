import { env } from "node:process";

export const PORT = parseInt(env.PORT || "3001", 10);
export const NODE_ENV = env.NODE_ENV || "development";

// Database configuration
export const DATABASE_URL = env.DATABASE_URL || "postgres://localhost/agrifitrade";
export const POSTGRES_HOST = env.POSTGRES_HOST || "localhost";
export const POSTGRES_PORT = env.POSTGRES_PORT || "5432";
export const POSTGRES_USER = env.POSTGRES_USER || "agriuser";
export const POSTGRES_PASSWORD = env.POSTGRES_PASSWORD || "securepassword";
export const POSTGRES_DB = env.POSTGRES_DB || "agrifitrade";

// JWT Configuration
export const JWT_SECRET = env.JWT_SECRET || "your-super-secret-jwt-key-change-in-production";
export const JWT_EXPIRES_IN = env.JWT_EXPIRES_IN || "7d";

// Redis configuration
export const REDIS_URL = env.REDIS_URL || "redis://localhost:6379";

// API Keys (Store these in environment variables in production!)
export const STRIPE_SECRET_KEY = env.STRIPE_SECRET_KEY || "";
export const COINGECKO_API_KEY = env.COINGECKO_API_KEY || "";
export const METAMASK_RPC_URL = env.METAMASK_RPC_URL || "";
export const ETHEREUM_NODE_URL = env.ETHEREUM_NODE_URL || "https://mainnet.infura.io/v3/YOUR_INFURA_KEY";

// Land Registry configuration
export const LAND_REGISTRY_API_URL = env.LAND_REGISTRY_API_URL || "";
export const LAND_REGISTRY_API_KEY = env.LAND_REGISTRY_API_KEY || "";

// Payment Gateway configuration
export const PAYMENT_GATEWAY_API_KEY = env.PAYMENT_GATEWAY_API_KEY || "";
export const PAYMENT_GATEWAY_SECRET = env.PAYMENT_GATEWAY_SECRET || "";

// CORS origins (comma-separated)
export const CORS_ORIGINS = env.CORS_ORIGINS || "http://localhost:3000,http://localhost:5173";

// Rate limiting
export const RATE_LIMIT_WINDOW_MS = parseInt(env.RATE_LIMIT_WINDOW_MS || "60000", 10);
export const RATE_LIMIT_MAX_REQUESTS = parseInt(env.RATE_LIMIT_MAX_REQUESTS || "100", 10);

// Audit log configuration
export const AUDIT_LOG_ENABLED = env.AUDIT_LOG_ENABLED !== "false";
export const AUDIT_LOG_RETENTION_DAYS = parseInt(env.AUDIT_LOG_RETENTION_DAYS || "365", 10);

// Multi-tenant configuration
export const MULTI_TENANT_ENABLED = env.MULTI_TENANT_ENABLED !== "false";
export const TENANT_HEADER_NAME = env.TENANT_HEADER_NAME || "X-Tenant-ID";

// Feature flags
export const FEATURE_NFT_MARKETPLACE = env.FEATURE_NFT_MARKETPLACE !== "false";
export const FEATURE_CONTRACT_AUTOMATION = env.FEATURE_CONTRACT_AUTOMATION !== "false";
export const FEATURE_SUPPLY_CHAIN_TRACKING = env.FEATURE_SUPPLY_CHAIN_TRACKING !== "false";

// Email configuration
export const EMAIL_FROM = env.EMAIL_FROM || "noreply@agrifi.trade";
export const EMAIL_SERVER_URL = env.EMAIL_SERVER_URL || "";
export const EMAIL_SERVER_USER = env.EMAIL_SERVER_USER || "";
export const EMAIL_SERVER_PASSWORD = env.EMAIL_SERVER_PASSWORD || "";

// File upload configuration
export const MAX_FILE_SIZE_MB = parseInt(env.MAX_FILE_SIZE_MB || "10", 10);
export const ALLOWED_FILE_TYPES = env.ALLOWED_FILE_TYPES || "image/*,application/pdf";
export const UPLOAD_DIR = env.UPLOAD_DIR || "./uploads";
