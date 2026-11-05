import { Routes } from '@angular/router';
import { authGuard, profileGuard } from './auth/auth.guard';
import { DashboardPage } from './pages/dashboard.page';
import { LoginPage } from './pages/login.page';
import { ProfilePage } from './pages/profile.page';
import { RegisterPage } from './pages/register.page';
import { roleGuard } from './auth/auth.guard';
import { FarmerWorkspacePage } from './pages/farmer-workspace.page';
import { MarketplacePage } from './pages/marketplace.page';
import { ListingDetailPage } from './pages/listing-detail.page';
import { OrderPage } from './pages/order.page';
import { OrdersPage } from './pages/orders.page';
import { OperationsPage } from './pages/operations.page';
import { FinancePage } from './pages/finance.page';

export const routes: Routes = [
  { path: 'login', component: LoginPage },
  { path: 'register', component: RegisterPage },
  { path: 'profile', component: ProfilePage, canActivate: [authGuard, profileGuard] },
  { path: 'marketplace', component: MarketplacePage, canActivate: [authGuard, roleGuard], data: { roles: ['buyer'] } },
  { path: 'listings/:id', component: ListingDetailPage, canActivate: [authGuard, roleGuard], data: { roles: ['buyer'] } },
  { path: 'farmer', component: FarmerWorkspacePage, canActivate: [authGuard, roleGuard], data: { roles: ['farmer'] } },
  { path: 'orders', component: OrdersPage, canActivate: [authGuard, roleGuard], data: { roles: ['buyer', 'farmer', 'operations_admin'] } },
  { path: 'orders/:id', component: OrderPage, canActivate: [authGuard, roleGuard], data: { roles: ['buyer', 'farmer', 'operations_admin'] } },
  { path: 'operations', component: OperationsPage, canActivate: [authGuard, roleGuard], data: { roles: ['operations_admin'] } },
  { path: 'finance', component: FinancePage, canActivate: [authGuard, roleGuard], data: { roles: ['finance_operator', 'operations_admin'] } },
  { path: '', component: DashboardPage, canActivate: [authGuard] },
  { path: '**', redirectTo: '' },
];
