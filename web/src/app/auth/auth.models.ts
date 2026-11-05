export type UserRole =
  | 'farmer'
  | 'buyer'
  | 'operations_admin'
  | 'finance_operator'
  | 'system';

export interface AuthenticatedUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  roles: UserRole[];
}

export interface TokenResponse {
  access: string;
  user?: AuthenticatedUser;
}
