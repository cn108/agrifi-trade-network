# API Testing Plan

## Purpose
Validate the backend API implementation before frontend integration.

## Endpoints to Test

### Products (`/api/v1/products/`)
- `GET /` - List all products
- `GET /{id}/` - Get product details
- `POST /` - Create new product (farmer only)
- `PUT /{id}/` - Update product
- `DELETE /{id}/` - Delete product

### Orders (`/api/v1/orders/`)
- `GET /` - List orders for authenticated user
- `POST /` - Create order
- `GET /{id}/` - Get order details

### Payments (`/api/v1/payments/`)
- `POST /` - Create payment (simulated)

### Reviews (`/api/v1/reviews/`)
- `POST /` - Submit review
- `GET /product/{product_id}/` - Get reviews for a product

### Analytics (`/api/v1/analytics/daily/`)
- `GET /` - Get daily analytics data

## Test Strategy

1. **Authentication Tests**
   - Register new user
   - Login and get JWT token
   - Use token in subsequent requests

2. **Product CRUD Tests**
   - Create product (as farmer)
   - Read product list and details
   - Update product
   - Delete product

3. **Order Flow Tests**
   - Read products
   - Create order
   - Read order
   - Cancel order

4. **Payment Simulation Tests**
   - Create payment
   - Verify payment record

5. **Review Tests**
   - Submit review
   - Read reviews for product

6. **Analytics Tests**
   - Read daily analytics

## Tools
- Postman collection or Insomnia
- Python requests library with pytest
- Swagger/OpenAPI documentation at `/api/v1/schema/`

## Expected Status Codes
- `200 OK` - Success (GET, PUT)
- `201 Created` - Resource created (POST)
- `204 No Content` - Deleted (DELETE)
- `400 Bad Request` - Validation error
- `401 Unauthorized` - Missing/invalid token
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found

## Next Steps
1. Run tests using Postman or Python
2. Verify all endpoints work correctly
3. Document any issues
4. Proceed to frontend integration