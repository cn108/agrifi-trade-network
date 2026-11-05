import { CurrencyPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { MarketplaceService, Listing } from '../data/marketplace.service';

@Component({
  imports: [CurrencyPipe, ReactiveFormsModule, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-4xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/marketplace">← Marketplace</a>
      @if (loading()) {
        <p class="mt-8 rounded-2xl bg-white p-8 text-slate-500">Loading offer…</p>
      } @else if (errorMessage() && !listing()) {
        <p class="mt-8 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{{ errorMessage() }}</p>
      } @else if (listing(); as offer) {
        <div class="mt-7 grid gap-6 lg:grid-cols-[1.3fr_0.7fr]">
          <article class="rounded-2xl border border-slate-200 bg-white p-7">
            <span class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">Seller offer</span>
            <h1 class="mt-4 text-3xl font-semibold tracking-tight text-slate-900">{{ offer.name }}</h1>
            <p class="mt-2 text-slate-500">Offered by {{ offer.seller_name || 'AgriFi farmer' }}</p>
            <p class="mt-7 whitespace-pre-line text-sm leading-7 text-slate-700">
              {{ offer.description || 'No description provided.' }}
            </p>
            <p class="mt-8 text-xs text-slate-500">Unit: {{ offer.unit_code }} · Currency: {{ offer.currency }}</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">
              {{ offer.unit_price_minor / 100 | currency: offer.currency : 'symbol' : '1.2-2' }}
              <span class="text-sm font-normal text-slate-500">per {{ offer.unit_code }}</span>
            </p>
            <p class="mt-1 text-sm text-slate-600">Available: {{ offer.available_quantity ?? '—' }} {{ offer.unit_code }}</p>
            <p class="mt-4 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
              Displayed availability is indicative; the API validates quantity and calculates totals at checkout.
            </p>
          </article>
          <section class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Request this offer</h2>
            <p class="mt-1 text-sm text-slate-500">Checkout creates one single-seller order.</p>
            @if (errorMessage()) {
              <p class="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800" role="alert">{{ errorMessage() }}</p>
            }
            <form class="mt-5 space-y-4" [formGroup]="form" (ngSubmit)="checkout(offer)">
              <label class="block text-sm font-medium text-slate-700">
                Quantity ({{ offer.unit_code }})
                <input class="form-input" formControlName="quantity" min="0.001" step="0.001" type="number" />
              </label>
              <label class="block text-sm font-medium text-slate-700">
                Delivery address
                <textarea class="form-input min-h-24" formControlName="delivery_address" maxlength="1000"></textarea>
              </label>
              <label class="block text-sm font-medium text-slate-700">
                Notes <span class="font-normal text-slate-400">(optional)</span>
                <textarea class="form-input min-h-20" formControlName="notes" maxlength="1000"></textarea>
              </label>
              <button class="w-full rounded-xl bg-emerald-800 px-4 py-3 font-semibold text-white hover:bg-emerald-900 disabled:opacity-60"
                [disabled]="submitting() || form.invalid" type="submit">
                {{ submitting() ? 'Placing order…' : 'Place order' }}
              </button>
            </form>
            <p class="mt-4 text-xs leading-5 text-slate-500">The server calculates price and total from the current listing. Your operation key is reused if you retry.</p>
          </section>
        </div>
      }
    </main>
  `,
  styles: [`
    .form-input { display: block; width: 100%; margin-top: 0.5rem; border: 1px solid #cbd5e1; border-radius: 0.75rem; background: white; padding: 0.75rem 1rem; outline: none; }
    .form-input:focus { border-color: #047857; box-shadow: 0 0 0 4px rgb(4 120 87 / 10%); }
  `],
})
export class ListingDetailPage implements OnInit {
  private readonly api = inject(MarketplaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly formBuilder = inject(FormBuilder);
  readonly listing = signal<Listing | null>(null);
  readonly loading = signal(true);
  readonly submitting = signal(false);
  readonly errorMessage = signal('');
  private requestId = crypto.randomUUID();
  readonly form = this.formBuilder.nonNullable.group({
    quantity: ['1', Validators.required],
    delivery_address: ['', Validators.required],
    notes: [''],
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.errorMessage.set('Listing identifier is missing.');
      this.loading.set(false);
      return;
    }
    this.api.listing(id).subscribe({
      next: (listing) => {
        this.listing.set(listing);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set('This listing is not available to your account.');
        this.loading.set(false);
      },
    });
  }

  checkout(offer: Listing): void {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }
    this.errorMessage.set('');
    this.submitting.set(true);
    this.api.createOrder({
      client_request_id: this.requestId,
      items: [{ listing: offer.id, quantity: this.form.controls.quantity.value }],
      delivery_address: this.form.controls.delivery_address.value,
      notes: this.form.controls.notes.value,
    }).pipe(finalize(() => this.submitting.set(false))).subscribe({
      next: (order) => {
        this.requestId = crypto.randomUUID();
        void this.router.navigate(['/orders', order.id]);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 409
            ? 'The request conflicts with current offer or stock. Check the listing and retry.'
            : 'Checkout failed. If the result is uncertain, retry without changing the order request.',
        );
      },
    });
  }
}
