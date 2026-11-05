import { CurrencyPipe, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../auth/auth.service';
import { MarketplaceService, OrderSummary } from '../data/marketplace.service';

@Component({
  imports: [CurrencyPipe, DatePipe, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-6xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/">← Dashboard</a>
      <div class="mt-6">
        <p class="text-sm font-semibold text-emerald-700">Order management</p>
        <h1 class="mt-1 text-3xl font-semibold tracking-tight text-slate-900">Order history</h1>
        <p class="mt-2 text-sm text-slate-500">Orders visible to your authenticated account.</p>
      </div>
      @if (errorMessage()) {
        <p class="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{{ errorMessage() }}</p>
      }
      @if (loading()) {
        <p class="mt-8 rounded-2xl bg-white p-8 text-slate-500">Loading orders…</p>
      } @else if (orders().length === 0) {
        <div class="mt-8 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
          <p class="font-medium text-slate-800">No orders yet</p>
          <p class="mt-1 text-sm text-slate-500">Orders you place or supply will appear here.</p>
          @if (isBuyer()) {
            <a class="mt-4 inline-flex rounded-xl bg-emerald-800 px-4 py-2.5 text-sm font-semibold text-white" routerLink="/marketplace">
              Browse marketplace
            </a>
          }
        </div>
      } @else {
        <div class="mt-8 overflow-hidden rounded-2xl border border-slate-200 bg-white">
          @for (order of orders(); track order.id) {
            <a class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-5 py-5 last:border-0 hover:bg-slate-50"
               [routerLink]="['/orders', order.id]">
              <div>
                <p class="font-semibold text-slate-900">Order {{ order.id.slice(0, 8) }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ order.created_at | date: 'medium' }} · {{ order.items.length }} item(s)</p>
              </div>
              <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold capitalize text-slate-700">{{ order.status }}</span>
              <p class="font-semibold text-slate-900">{{ order.total_minor / 100 | currency: order.currency : 'symbol' : '1.2-2' }}</p>
              <span class="text-sm font-semibold text-emerald-800">View details →</span>
            </a>
          }
        </div>
      }
    </main>
  `,
})
export class OrdersPage implements OnInit {
  private readonly api = inject(MarketplaceService);
  private readonly auth = inject(AuthService);
  readonly orders = signal<OrderSummary[]>([]);
  readonly loading = signal(true);
  readonly errorMessage = signal('');

  ngOnInit(): void {
    const roles = this.auth.user()?.roles ?? [];
    if (!roles.some((role) => ['buyer', 'farmer', 'operations_admin'].includes(role))) {
      this.errorMessage.set('Orders are only available to buyers, farmers, and operations administrators.');
      this.loading.set(false);
      return;
    }
    this.api.orders().subscribe({
      next: (orders) => {
        this.orders.set(orders);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'Your account cannot access order records.'
            : 'Order history could not be loaded.',
        );
        this.loading.set(false);
      },
    });
  }

  isBuyer(): boolean {
    return this.auth.user()?.roles.includes('buyer') ?? false;
  }
}
