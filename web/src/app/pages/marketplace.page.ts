import { CurrencyPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MarketplaceService, CropCategory, Listing } from '../data/marketplace.service';

@Component({
  imports: [CurrencyPipe, ReactiveFormsModule, RouterLink],
  template: `
    <main class="catalogue-page mx-auto min-h-screen max-w-7xl px-5 py-8 lg:px-8">
      <a class="catalogue-back text-sm" routerLink="/">← <span>Dashboard</span></a>
      <div class="catalogue-head mt-5">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.16em] text-emerald-700">Buyer catalogue</p>
          <h1 class="marketplace-heading mt-2 text-3xl font-semibold tracking-tight text-slate-900">Browse agricultural offers</h1>
          <p class="mt-2 max-w-xl text-sm leading-6 text-slate-600">Seller offers from the live catalogue. Stock is checked atomically at checkout.</p>
        </div>
        <form class="flex flex-wrap gap-2" [formGroup]="filters" role="search" aria-label="Filter marketplace offers">
          <input class="filter-input" formControlName="search" placeholder="Search crops" />
          <select class="filter-input" formControlName="category">
            <option value="">All categories</option>
            @for (category of categories(); track category.id) {
              <option [value]="category.id">{{ category.name }}</option>
            }
          </select>
        </form>
      </div>

      @if (errorMessage()) {
        <p class="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {{ errorMessage() }}
        </p>
      }
      @if (loading()) {
        <p class="mt-8 rounded-xl bg-white p-8 text-slate-500">Loading active offers…</p>
      } @else if (filteredListings().length === 0) {
        <div class="mt-8 rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
          <p class="font-medium text-slate-800">No matching offers</p>
          <p class="mt-1 text-sm text-slate-500">Try another search or check back later.</p>
        </div>
      } @else {
        <div class="mt-8 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          @for (listing of filteredListings(); track listing.id) {
            <article class="catalogue-card flex flex-col p-5">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-xs font-semibold uppercase tracking-wide text-emerald-700">{{ categoryName(listing.category) }}</p>
                  <h2 class="mt-2 text-lg font-semibold text-slate-900">{{ listing.name }}</h2>
                  <p class="mt-1 text-sm text-slate-500">Offered by {{ listing.seller_name || 'AgriFi farmer' }}</p>
                </div>
                <span class="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">Active offer</span>
              </div>
              <p class="mt-4 line-clamp-3 min-h-14 text-sm leading-6 text-slate-600">
                {{ listing.description || 'The seller has not added a description.' }}
              </p>
              <div class="mt-auto flex items-end justify-between border-t border-slate-100 pt-4">
                <div>
                  <p class="text-xs text-slate-500">Price per {{ listing.unit_code }}</p>
                  <p class="mt-1 text-xl font-semibold text-slate-900">
                    {{ listing.unit_price_minor / 100 | currency: listing.currency : 'symbol' : '1.2-2' }}
                  </p>
                  <p class="mt-1 text-xs text-slate-500">Available: {{ listing.available_quantity ?? '—' }} {{ listing.unit_code }}</p>
                </div>
                <a class="catalogue-cta"
                   [routerLink]="['/listings', listing.id]">
                  View offer
                </a>
              </div>
            </article>
          }
        </div>
      }
    </main>
  `,
})
export class MarketplacePage implements OnInit {
  private readonly api = inject(MarketplaceService);
  private readonly formBuilder = inject(FormBuilder);
  readonly categories = signal<CropCategory[]>([]);
  readonly listings = signal<Listing[]>([]);
  readonly loading = signal(true);
  readonly errorMessage = signal('');
  readonly filters = this.formBuilder.nonNullable.group({ search: '', category: '' });

  ngOnInit(): void {
    this.api.categories().subscribe({
      next: (categories) => this.categories.set(categories),
      error: () => this.errorMessage.set('Crop categories could not be loaded.'),
    });
    this.api.listings().subscribe({
      next: (listings) => {
        this.listings.set(listings);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'Your account cannot browse marketplace listings.'
            : 'Marketplace listings could not be loaded.',
        );
        this.loading.set(false);
      },
    });
  }

  filteredListings(): Listing[] {
    const search = this.filters.controls.search.value.trim().toLowerCase();
    const category = this.filters.controls.category.value;
    return this.listings().filter((listing) => {
      const matchesSearch =
        !search ||
        listing.name.toLowerCase().includes(search) ||
        listing.description.toLowerCase().includes(search) ||
        listing.seller_name.toLowerCase().includes(search);
      return matchesSearch && (!category || listing.category === category);
    });
  }

  categoryName(id: string): string {
    return this.categories().find((category) => category.id === id)?.name ?? 'Crop';
  }
}
