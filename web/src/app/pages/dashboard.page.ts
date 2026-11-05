import { CurrencyPipe, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { AuthService } from '../auth/auth.service';
import { UserRole } from '../auth/auth.models';
import {
  CropCategory,
  FinancialRecord,
  LedgerAccount,
  Listing,
  MarketplaceService,
  OrderSummary,
} from '../data/marketplace.service';

@Component({
  imports: [CurrencyPipe, DatePipe, RouterLink],
  template: `
    <div class="dashboard-shell">
      <header class="workspace-header border-b border-emerald-950/10 bg-white">
        <div class="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
          <a class="flex items-center gap-3" routerLink="/">
            <span class="brand-mark">A</span>
            <span>
              <span class="block text-lg font-bold tracking-tight text-emerald-950">AgriFi</span>
              <span class="block text-xs text-slate-500">Trade Network</span>
            </span>
          </a>
          <div class="flex items-center gap-4">
            <div class="hidden text-right sm:block">
              <p class="text-sm font-semibold text-slate-800">{{ displayName() }}</p>
              <p class="text-xs text-slate-500">{{ roleLabels() }}</p>
            </div>
            @if (hasFarmerOrBuyerRole()) {
              <a
                class="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                routerLink="/profile"
              >
                Profile
              </a>
            }
            <button
              class="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              [disabled]="signingOut()"
              (click)="logout()"
              type="button"
            >
              {{ signingOut() ? 'Signing out…' : 'Sign out' }}
            </button>
          </div>
        </div>
      </header>

      <main class="workspace-main mx-auto max-w-7xl px-5 py-8 lg:px-8">
        <nav class="workspace-nav mb-7 flex flex-wrap gap-2" aria-label="Workspace navigation">
          @if (isBuyer()) {
            <a class="nav-link" routerLink="/marketplace">Marketplace</a>
          }
          @if (isFarmer()) {
            <a class="nav-link" routerLink="/farmer">Farmer workspace</a>
          }
          @if (canSeeOrders()) {
            <a class="nav-link" routerLink="/orders">Orders</a>
          }
          @if (isOperationsAdmin()) {
            <a class="nav-link" routerLink="/operations">Operations</a>
          }
          @if (canSeeFinance()) {
            <a class="nav-link" routerLink="/finance">Finance</a>
          }
        </nav>
        @if (logoutError()) {
          <div class="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {{ logoutError() }}
          </div>
        }
        <section class="dashboard-hero mb-7" aria-labelledby="dashboard-title">
          <div class="dashboard-hero-copy">
            <p class="dashboard-hero-eyebrow">Your AgriFi workspace</p>
            <h1 id="dashboard-title">{{ greeting() }}</h1>
            <p>Your trade activity, marketplace offers and account updates, all in one place.</p>
          </div>
          <span class="hero-orbit" aria-hidden="true">A</span>
        </section>

        @if (loadError()) {
          <div class="mb-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {{ loadError() }}
          </div>
        }

        @if (loading()) {
          <div class="rounded-2xl border border-slate-200 bg-white p-8 text-slate-500">
            Loading your workspace…
          </div>
        } @else {
          <section class="workspace-metrics grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Workspace summary">
            @if (canBrowseListings()) {
              <article class="metric-card">
                <p class="text-sm text-slate-500">{{ isFarmer() ? 'Your listings' : 'Active listings' }}</p>
                <p class="mt-2 text-3xl font-semibold text-slate-900">{{ listings().length }}</p>
                <p class="mt-1 text-xs text-slate-500">From the current marketplace API response</p>
              </article>
              <article class="metric-card">
                <p class="text-sm text-slate-500">Crop categories</p>
                <p class="mt-2 text-3xl font-semibold text-slate-900">{{ categories().length }}</p>
                <p class="mt-1 text-xs text-slate-500">Active catalogue categories</p>
              </article>
            }
            @if (orders().length > 0 || canSeeOrders()) {
              <article class="metric-card">
                <p class="text-sm text-slate-500">Orders</p>
                <p class="mt-2 text-3xl font-semibold text-slate-900">{{ orders().length }}</p>
                <p class="mt-1 text-xs text-slate-500">Orders visible to your account</p>
              </article>
            }
            @if (canSeeFinance()) {
              <article class="metric-card border-amber-200 bg-amber-50">
                <p class="text-sm font-medium text-amber-900">Simulated finance</p>
                <p class="mt-2 text-3xl font-semibold text-amber-950">{{ financeRecordCount() }}</p>
                <p class="mt-1 text-xs text-amber-800">Payments, refunds and settlements (not real money)</p>
              </article>
            }
          </section>

          @if (canBrowseListings()) {
            <section class="mt-10">
              <div class="mb-4 flex items-end justify-between gap-4">
                <div>
                  <h2 class="text-xl font-semibold text-slate-900">
                    {{ isFarmer() ? 'Your listings' : 'Marketplace' }}
                  </h2>
                  <p class="mt-1 text-sm text-slate-500">
                    {{ isFarmer() ? 'Manage listings owned by your account.' : 'Current active offers from the catalogue.' }}
                  </p>
                </div>
              </div>
              @if (listings().length === 0) {
                <div class="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
                  <p class="font-medium text-slate-800">No listings to show yet</p>
                  <p class="mt-1 text-sm text-slate-500">
                    Listings will appear here when they are available through the API.
                  </p>
                </div>
              } @else {
                <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  @for (listing of listings(); track listing.id) {
                    <article class="listing-card rounded-2xl p-5">
                      <div class="flex items-start justify-between gap-3">
                        <div>
                          <h3 class="font-semibold text-slate-900">{{ listing.name }}</h3>
                          <p class="mt-1 text-sm text-slate-500">{{ listing.seller_name || 'AgriFi farmer' }}</p>
                        </div>
                        <span class="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800">
                          {{ listing.status }}
                        </span>
                      </div>
                      <p class="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-slate-600">
                        {{ listing.description || 'No description provided.' }}
                      </p>
                      <div class="mt-5 flex items-end justify-between border-t border-slate-100 pt-4">
                        <div>
                          <p class="text-xs text-slate-500">Price per {{ listing.unit_code }}</p>
                          <p class="mt-1 text-lg font-semibold text-slate-900">
                            {{ listing.unit_price_minor / 100 | currency: listing.currency : 'symbol' : '1.2-2' }}
                          </p>
                        </div>
                        <p class="text-xs text-slate-500">Seller offer</p>
                      </div>
                    </article>
                  }
                </div>
              }
            </section>
          }

          @if (canSeeOrders()) {
            <section class="mt-10">
              <h2 class="mb-4 text-xl font-semibold text-slate-900">Recent orders</h2>
              @if (orders().length === 0) {
                <div class="rounded-2xl border border-dashed border-slate-300 bg-white p-7 text-sm text-slate-500">
                  No orders are available for this account.
                </div>
              } @else {
                <div class="workspace-panel overflow-hidden">
                  @for (order of orders(); track order.id) {
                    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 last:border-0">
                      <div>
                        <p class="font-medium text-slate-900">Order {{ order.id.slice(0, 8) }}</p>
                        <p class="mt-1 text-xs text-slate-500">{{ order.created_at | date: 'mediumDate' }}</p>
                      </div>
                      <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                        {{ order.status }}
                      </span>
                      <p class="font-semibold text-slate-900">
                        {{ order.total_minor / 100 | currency: order.currency : 'symbol' : '1.2-2' }}
                      </p>
                    </div>
                  }
                </div>
              }
            </section>
          }

          @if (canSeeFinance()) {
            <section class="mt-10">
              <div class="mb-4">
                <h2 class="text-xl font-semibold text-slate-900">Simulated finance records</h2>
                <p class="mt-1 text-sm text-amber-800">
                  These internal records are simulated. No funds are collected, held or transferred.
                </p>
              </div>
              <div class="grid gap-4 lg:grid-cols-2">
                <article class="workspace-panel p-5">
                  <h3 class="font-semibold text-slate-900">Ledger accounts</h3>
                  <p class="mt-1 text-sm text-slate-500">Balances are derived from posted journal entries.</p>
                  <div class="mt-4 space-y-3">
                    @for (account of ledgerAccounts(); track account.code) {
                      <div class="flex justify-between gap-3 border-t border-slate-100 pt-3 text-sm">
                        <span class="text-slate-700">{{ account.name }} <span class="text-xs text-slate-400">({{ account.code }})</span></span>
                        <span class="font-medium text-slate-900">
                          {{ account.debit_balance_minor / 100 | currency: account.currency : 'symbol' : '1.2-2' }}
                        </span>
                      </div>
                    }
                    @if (ledgerAccounts().length === 0) {
                      <p class="border-t border-slate-100 pt-3 text-sm text-slate-500">No ledger accounts are available.</p>
                    }
                  </div>
                </article>
                <article class="workspace-panel p-5">
                  <h3 class="font-semibold text-slate-900">Record counts</h3>
                  <div class="mt-4 space-y-3 text-sm">
                    <p class="flex justify-between border-t border-slate-100 pt-3">
                      <span class="text-slate-600">Simulated payments</span><strong>{{ payments().length }}</strong>
                    </p>
                    <p class="flex justify-between border-t border-slate-100 pt-3">
                      <span class="text-slate-600">Simulated refunds</span><strong>{{ refunds().length }}</strong>
                    </p>
                    <p class="flex justify-between border-t border-slate-100 pt-3">
                      <span class="text-slate-600">Simulated settlements</span><strong>{{ settlements().length }}</strong>
                    </p>
                  </div>
                </article>
              </div>
            </section>
          }
        }
      </main>
    </div>
  `,
})
export class DashboardPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly api = inject(MarketplaceService);
  private readonly router = inject(Router);

  readonly listings = signal<Listing[]>([]);
  readonly categories = signal<CropCategory[]>([]);
  readonly orders = signal<OrderSummary[]>([]);
  readonly payments = signal<FinancialRecord[]>([]);
  readonly refunds = signal<FinancialRecord[]>([]);
  readonly settlements = signal<FinancialRecord[]>([]);
  readonly ledgerAccounts = signal<LedgerAccount[]>([]);
  readonly loading = signal(true);
  readonly signingOut = signal(false);
  readonly loadError = signal('');
  readonly logoutError = signal('');

  private readonly roles = this.auth.user()?.roles ?? [];

  ngOnInit(): void {
    const userRoles = this.roles;
    const listingRequest = this.canBrowseListings()
      ? this.api.listings(userRoles.includes('farmer'))
      : of([]);
    const categoryRequest = this.canBrowseListings() ? this.api.categories() : of([]);
    const orderRequest = this.canSeeOrders() ? this.api.orders() : of([]);
    const financeRequests = this.canSeeFinance()
      ? forkJoin({
          payments: this.api.payments(),
          refunds: this.api.refunds(),
          settlements: this.api.settlements(),
          ledgerAccounts: this.api.ledgerAccounts(),
        })
      : of({ payments: [], refunds: [], settlements: [], ledgerAccounts: [] });

    forkJoin({
      listings: listingRequest,
      categories: categoryRequest,
      orders: orderRequest,
      finance: financeRequests,
    })
      .subscribe({
        next: (data) => {
          this.listings.set(data.listings);
          this.categories.set(data.categories);
          this.orders.set(data.orders);
          this.payments.set(data.finance.payments);
          this.refunds.set(data.finance.refunds);
          this.settlements.set(data.finance.settlements);
          this.ledgerAccounts.set(data.finance.ledgerAccounts);
          this.loading.set(false);
        },
        error: (error: unknown) => {
          this.loadError.set(
            error instanceof HttpErrorResponse && error.status === 403
              ? 'Your account does not have permission to load one or more dashboard sections.'
              : 'Dashboard data could not be loaded. Please try again.',
          );
          this.loading.set(false);
        },
      });
  }

  displayName(): string {
    const user = this.auth.user();
    return user ? `${user.first_name} ${user.last_name}`.trim() || user.email : '';
  }

  greeting(): string {
    const user = this.auth.user();
    return user?.first_name ? `Welcome, ${user.first_name}` : 'Welcome to AgriFi';
  }

  roleLabels(): string {
    return this.roles.map((role) => role.replace('_', ' ')).join(' · ');
  }

  isFarmer(): boolean {
    return this.roles.includes('farmer');
  }

  canBrowseListings(): boolean {
    return this.roles.some((role) =>
      ['farmer', 'buyer', 'operations_admin'].includes(role),
    );
  }

  canSeeOrders(): boolean {
    return this.roles.some((role) =>
      ['farmer', 'buyer', 'operations_admin'].includes(role),
    );
  }

  canSeeFinance(): boolean {
    return this.roles.some((role) => ['finance_operator', 'operations_admin'].includes(role));
  }

  isBuyer(): boolean {
    return this.roles.includes('buyer');
  }

  isOperationsAdmin(): boolean {
    return this.roles.includes('operations_admin');
  }

  hasFarmerOrBuyerRole(): boolean {
    return this.roles.includes('farmer') || this.roles.includes('buyer');
  }

  financeRecordCount(): number {
    return this.payments().length + this.refunds().length + this.settlements().length;
  }

  logout(): void {
    this.signingOut.set(true);
    this.logoutError.set('');
    this.auth.logout().subscribe({
      next: () => void this.router.navigate(['/login']),
      error: () => {
        this.logoutError.set('Sign-out could not be confirmed by the API. Please retry.');
        this.signingOut.set(false);
      },
    });
  }
}
