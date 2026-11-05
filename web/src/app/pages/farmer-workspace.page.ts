import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import {
  CropCategory,
  HarvestBatch,
  Listing,
  ListingInput,
  ListingStock,
  MarketplaceService,
} from '../data/marketplace.service';

const UNITS = ['kg', 'tonne', 'bag', 'crate', 'piece'];

@Component({
  imports: [DatePipe, ReactiveFormsModule, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-7xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/">← Dashboard</a>
      <div class="mt-6">
        <p class="text-sm font-semibold text-emerald-700">Farmer workspace</p>
        <h1 class="mt-1 text-3xl font-semibold tracking-tight text-slate-900">Supply and listings</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
          Record a harvest batch for operations review, publish a seller offer, and allocate accepted
          supply to that offer. Available quantity is calculated from the stock ledger.
        </p>
      </div>

      @if (message()) {
        <p class="mt-6 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">
          {{ message() }}
        </p>
      }
      @if (errorMessage()) {
        <p class="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {{ errorMessage() }}
        </p>
      }

      <div class="mt-8 grid gap-6 xl:grid-cols-2">
        <section class="rounded-2xl border border-slate-200 bg-white p-6">
          <div class="mb-5">
            <h2 class="text-lg font-semibold text-slate-900">
              {{ correctingBatch() ? 'Correct rejected batch' : 'Record harvest batch' }}
            </h2>
            <p class="mt-1 text-sm text-slate-500">Each submission keeps its operation ID for safe retries.</p>
            @if (correctingBatch(); as original) {
              <p class="mt-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900" data-testid="correction-banner">
                Correcting rejected batch {{ original.id.slice(0, 8) }}. Reason: {{ original.rejection_reason || 'none given' }}.
                The original stays on record; this creates a new submission linked to it.
                <button class="ml-2 underline" type="button" (click)="cancelCorrection()">Cancel</button>
              </p>
            }
          </div>
          @if (categories().length === 0) {
            <p class="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">No active categories are available.</p>
          } @else {
            <form class="grid gap-4 sm:grid-cols-2" [formGroup]="batchForm" (ngSubmit)="submitBatch()">
              <label class="text-sm font-medium text-slate-700 sm:col-span-2">
                Crop category
                <select class="form-input" formControlName="category">
                  @for (category of categories(); track category.id) {
                    <option [value]="category.id">{{ category.name }}</option>
                  }
                </select>
              </label>
              <label class="text-sm font-medium text-slate-700">
                Quantity
                <input class="form-input" formControlName="quantity" min="0.001" step="0.001" type="number" />
              </label>
              <label class="text-sm font-medium text-slate-700">
                Unit
                <select class="form-input" formControlName="unit_code">
                  @for (unit of units; track unit) { <option [value]="unit">{{ unit }}</option> }
                </select>
              </label>
              <label class="text-sm font-medium text-slate-700">
                Harvest date
                <input class="form-input" formControlName="harvested_on" type="date" />
              </label>
              <label class="text-sm font-medium text-slate-700 sm:col-span-2">
                Notes <span class="font-normal text-slate-400">(optional)</span>
                <textarea class="form-input min-h-20" formControlName="notes" maxlength="2000"></textarea>
              </label>
              <button class="action-button sm:col-span-2 sm:justify-self-start" [disabled]="savingBatch() || batchForm.invalid">
                {{ savingBatch() ? 'Submitting…' : correctingBatch() ? 'Submit correction for review' : 'Submit batch for review' }}
              </button>
            </form>
          }
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-6">
          <div class="mb-5">
            <h2 class="text-lg font-semibold text-slate-900">{{ editingListingId() ? 'Edit listing' : 'Create listing' }}</h2>
            <p class="mt-1 text-sm text-slate-500">Prices are entered in integer kobo per unit.</p>
          </div>
          @if (categories().length === 0) {
            <p class="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">A category is needed before publishing.</p>
          } @else {
            <form class="grid gap-4 sm:grid-cols-2" [formGroup]="listingForm" (ngSubmit)="saveListing()">
              <label class="text-sm font-medium text-slate-700 sm:col-span-2">
                Listing name
                <input class="form-input" formControlName="name" maxlength="150" />
              </label>
              <label class="text-sm font-medium text-slate-700 sm:col-span-2">
                Category
                <select class="form-input" formControlName="category">
                  @for (category of categories(); track category.id) {
                    <option [value]="category.id">{{ category.name }}</option>
                  }
                </select>
              </label>
              <label class="text-sm font-medium text-slate-700">
                Unit
                <select class="form-input" formControlName="unit_code">
                  @for (unit of units; track unit) { <option [value]="unit">{{ unit }}</option> }
                </select>
              </label>
              <label class="text-sm font-medium text-slate-700">
                Price (kobo per unit)
                <input class="form-input" formControlName="unit_price_minor" min="1" step="1" type="number" />
              </label>
              <label class="text-sm font-medium text-slate-700">
                Listing status
                <select class="form-input" formControlName="status">
                  <option value="draft">Draft</option>
                  <option value="active">Active</option>
                  <option value="paused">Paused</option>
                  <option value="archived">Archived</option>
                </select>
              </label>
              <label class="text-sm font-medium text-slate-700 sm:col-span-2">
                Description
                <textarea class="form-input min-h-20" formControlName="description"></textarea>
              </label>
              <div class="flex flex-wrap gap-3 sm:col-span-2">
                <button class="action-button" [disabled]="savingListing() || listingForm.invalid">
                  {{ savingListing() ? 'Saving…' : editingListingId() ? 'Save listing changes' : 'Create listing' }}
                </button>
                @if (editingListingId()) {
                  <button class="secondary-button" (click)="cancelEdit()" type="button">Cancel edit</button>
                }
              </div>
            </form>
          }
        </section>
      </div>

      <section class="mt-8 rounded-2xl border border-slate-200 bg-white p-6">
        <div class="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">My harvest batches</h2>
            <p class="mt-1 text-sm text-slate-500">Accepted batches can supply listings; rejected batches include the review reason.</p>
          </div>
          <button class="secondary-button" (click)="load()" type="button">Refresh</button>
        </div>
        @if (loading()) {
          <p class="py-5 text-sm text-slate-500">Loading supply records…</p>
        } @else if (batches().length === 0) {
          <p class="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500">No batches recorded yet.</p>
        } @else {
          <div class="divide-y divide-slate-100">
            @for (batch of batches(); track batch.id) {
              <article class="flex flex-wrap items-center justify-between gap-3 py-4" [attr.data-batch-id]="batch.id">
                <div>
                  <p class="font-semibold text-slate-900">{{ categoryName(batch.category) }} · {{ batch.quantity }} {{ batch.unit_code }}</p>
                  <p class="mt-1 text-xs text-slate-500">Harvested {{ batch.harvested_on | date: 'mediumDate' }}</p>
                  @if (batch.resubmission_of) {
                    <p class="mt-1 text-xs text-slate-600" data-testid="correction-of">
                      Correction of rejected batch {{ batch.resubmission_of.slice(0, 8) }}
                    </p>
                  }
                  @if (batch.status === 'rejected') {
                    <p class="mt-1 text-sm text-red-700" data-testid="rejection-reason">
                      Rejected: {{ batch.rejection_reason || 'no reason given' }}
                    </p>
                    @if (correctionOf(batch); as correction) {
                      <p class="mt-1 text-xs text-slate-600" data-testid="corrected-by">
                        Corrected by {{ correction.id.slice(0, 8) }} (status: {{ correction.status }})
                      </p>
                    }
                  }
                </div>
                <div class="flex items-center gap-2">
                  @if (batch.status === 'rejected' && !batch.correction_id) {
                    <button class="secondary-button" type="button" data-testid="start-correction" (click)="startCorrection(batch)">
                      Create correction
                    </button>
                  }
                  <span class="rounded-full px-3 py-1 text-xs font-semibold capitalize"
                    [class]="batch.status === 'accepted' ? 'bg-emerald-50 text-emerald-800' : batch.status === 'rejected' ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-900'">
                    {{ batch.status }}
                  </span>
                </div>
              </article>
            }
          </div>
        }
      </section>

      <section class="mt-8 rounded-2xl border border-slate-200 bg-white p-6">
        <div class="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">My listings and available stock</h2>
            <p class="mt-1 text-sm text-slate-500">Stock is ledger-derived; reserved quantities are excluded from availability.</p>
          </div>
          <button class="secondary-button" (click)="load()" type="button">Refresh inventory</button>
        </div>
        @if (listings().length === 0) {
          <p class="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-500">Create a listing to start offering supply.</p>
        } @else {
          <div class="grid gap-4 lg:grid-cols-2">
            @for (listing of listings(); track listing.id) {
              <article class="rounded-xl border border-slate-200 p-5">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 class="font-semibold text-slate-900">{{ listing.name }}</h3>
                    <p class="mt-1 text-sm text-slate-500">{{ categoryName(listing.category) }} · {{ listing.status }}</p>
                  </div>
                  <button class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" (click)="editListing(listing)" type="button">
                    Edit
                  </button>
                </div>
                <div class="mt-4 grid grid-cols-3 gap-2 rounded-lg bg-slate-50 p-3 text-center">
                  <div><p class="text-xs text-slate-500">On hand</p><p class="mt-1 font-semibold">{{ stockFor(listing.id)?.on_hand ?? '—' }}</p></div>
                  <div><p class="text-xs text-slate-500">Reserved</p><p class="mt-1 font-semibold">{{ stockFor(listing.id)?.reserved ?? '—' }}</p></div>
                  <div><p class="text-xs text-slate-500">Available</p><p class="mt-1 font-semibold text-emerald-800">{{ stockFor(listing.id)?.available ?? '—' }}</p></div>
                </div>
                <form class="mt-4 grid gap-3 sm:grid-cols-[1fr_7rem_auto]" (submit)="moveStock($event, listing.id)">
                  <select class="form-input mt-0" [name]="'batch-' + listing.id" required>
                    <option value="">Accepted batch</option>
                    @for (batch of acceptedBatchesFor(listing); track batch.id) {
                      <option [value]="batch.id">{{ batch.quantity }} {{ batch.unit_code }} · {{ batch.id.slice(0, 8) }}</option>
                    }
                  </select>
                  <input class="form-input mt-0" [name]="'quantity-' + listing.id" min="0.001" placeholder="Quantity" required step="0.001" type="number" />
                  <div class="flex gap-2">
                    <button class="secondary-button" [disabled]="movingListingId() === listing.id" name="operation" value="allocate" type="submit">Allocate</button>
                    <button class="secondary-button" [disabled]="movingListingId() === listing.id" name="operation" value="deallocate" type="submit">Return</button>
                  </div>
                </form>
              </article>
            }
          </div>
        }
      </section>
    </main>
  `,
  styles: [`
    .form-input {
      display: block; width: 100%; margin-top: 0.5rem; border: 1px solid #cbd5e1;
      border-radius: 0.75rem; background: white; padding: 0.7rem 0.9rem; outline: none;
    }
    .form-input:focus { border-color: #047857; box-shadow: 0 0 0 4px rgb(4 120 87 / 10%); }
    .action-button { border-radius: 0.75rem; background: #065f46; padding: 0.7rem 1rem; color: white; font-weight: 600; }
    .action-button:disabled { opacity: 0.6; }
    .secondary-button { border: 1px solid #cbd5e1; border-radius: 0.65rem; padding: 0.55rem 0.75rem; color: #334155; font-size: 0.8rem; font-weight: 600; }
    .secondary-button:disabled { opacity: 0.55; }
  `],
})
export class FarmerWorkspacePage implements OnInit {
  private readonly formBuilder = inject(FormBuilder);
  private readonly api = inject(MarketplaceService);
  readonly units = UNITS;
  readonly categories = signal<CropCategory[]>([]);
  readonly batches = signal<HarvestBatch[]>([]);
  readonly listings = signal<Listing[]>([]);
  readonly stocks = signal<Record<string, ListingStock>>({});
  readonly loading = signal(true);
  readonly savingBatch = signal(false);
  readonly savingListing = signal(false);
  readonly movingListingId = signal('');
  readonly editingListingId = signal('');
  readonly message = signal('');
  readonly errorMessage = signal('');
  readonly batchOperationId = signal(crypto.randomUUID());
  readonly correctingBatchId = signal('');
  readonly correctingBatch = computed(
    () => this.batches().find((batch) => batch.id === this.correctingBatchId()) ?? null,
  );
  readonly stockOperationIds = signal<Record<string, string>>({});

  readonly batchForm = this.formBuilder.nonNullable.group({
    category: ['', Validators.required],
    quantity: ['', Validators.required],
    unit_code: ['kg', Validators.required],
    harvested_on: ['', Validators.required],
    notes: [''],
  });
  readonly listingForm = this.formBuilder.nonNullable.group({
    category: ['', Validators.required],
    name: ['', [Validators.required, Validators.maxLength(150)]],
    description: [''],
    unit_code: ['kg', Validators.required],
    unit_price_minor: [1, [Validators.required, Validators.min(1)]],
    status: ['draft', Validators.required],
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    forkJoin({
      categories: this.api.categories(),
      batches: this.api.harvestBatches(),
      listings: this.api.listings(true),
    }).subscribe({
      next: ({ categories, batches, listings }) => {
        this.categories.set(categories);
        this.batches.set(batches);
        this.listings.set(listings);
        if (!this.batchForm.controls.category.value && categories.length) {
          this.batchForm.controls.category.setValue(categories[0].id);
          this.listingForm.controls.category.setValue(categories[0].id);
        }
        if (listings.length === 0) {
          this.stocks.set({});
          this.loading.set(false);
          return;
        }
        forkJoin(listings.map((listing) => this.api.listingStock(listing.id))).subscribe({
          next: (stocks) => {
            this.stocks.set(Object.fromEntries(stocks.map((stock) => [stock.listing, stock])));
            this.loading.set(false);
          },
          error: () => {
            this.stocks.set({});
            this.errorMessage.set('Listings loaded, but stock availability could not be retrieved.');
            this.loading.set(false);
          },
        });
      },
      error: () => {
        this.errorMessage.set('Farmer records could not be loaded. Please retry.');
        this.loading.set(false);
      },
    });
  }

  correctionOf(batch: HarvestBatch): HarvestBatch | null {
    if (!batch.correction_id) {
      return null;
    }
    return this.batches().find((candidate) => candidate.id === batch.correction_id) ?? null;
  }

  startCorrection(batch: HarvestBatch): void {
    if (batch.status !== 'rejected' || batch.correction_id) {
      return;
    }
    this.message.set('');
    this.errorMessage.set('');
    this.correctingBatchId.set(batch.id);
    // The rejected submission owns its own key; a correction is a new operation.
    this.batchOperationId.set(crypto.randomUUID());
    this.batchForm.patchValue({
      category: batch.category,
      quantity: batch.quantity,
      unit_code: batch.unit_code,
      harvested_on: batch.harvested_on,
      notes: batch.notes,
    });
  }

  cancelCorrection(): void {
    this.correctingBatchId.set('');
    this.batchOperationId.set(crypto.randomUUID());
    this.batchForm.patchValue({ quantity: '', harvested_on: '', notes: '' });
  }

  submitBatch(): void {
    if (this.batchForm.invalid || this.savingBatch()) {
      this.batchForm.markAllAsTouched();
      return;
    }
    this.message.set('');
    this.errorMessage.set('');
    this.savingBatch.set(true);
    const original = this.correctingBatchId();
    this.api
      .createHarvestBatch({
        ...this.batchForm.getRawValue(),
        client_sync_id: this.batchOperationId(),
        ...(original ? { resubmission_of: original } : {}),
      })
      .subscribe({
        next: () => {
          this.message.set(original ? 'Correction submitted for operations review.' : 'Batch submitted for operations review.');
          this.correctingBatchId.set('');
          this.batchForm.controls.quantity.setValue('');
          this.batchForm.controls.harvested_on.setValue('');
          this.batchForm.controls.notes.setValue('');
          this.batchOperationId.set(crypto.randomUUID());
          this.savingBatch.set(false);
          this.load();
        },
        error: (error: unknown) => {
          this.errorMessage.set(this.describeError(error, 'Batch submission failed. Retry safely; the same operation key will be reused.'));
          this.savingBatch.set(false);
        },
      });
  }

  saveListing(): void {
    if (this.listingForm.invalid || this.savingListing()) {
      this.listingForm.markAllAsTouched();
      return;
    }
    this.message.set('');
    this.errorMessage.set('');
    this.savingListing.set(true);
    const operation = this.editingListingId()
      ? this.api.updateListing(this.editingListingId(), this.listingForm.getRawValue())
      : this.api.createListing(this.listingForm.getRawValue());
    operation.subscribe({
      next: () => {
        this.message.set(this.editingListingId() ? 'Listing updated.' : 'Listing created.');
        this.cancelEdit();
        this.savingListing.set(false);
        this.load();
      },
      error: (error: unknown) => {
        this.errorMessage.set(this.describeError(error, 'Listing could not be saved.'));
        this.savingListing.set(false);
      },
    });
  }

  editListing(listing: Listing): void {
    this.editingListingId.set(listing.id);
    this.listingForm.patchValue({
      category: listing.category,
      name: listing.name,
      description: listing.description,
      unit_code: listing.unit_code,
      unit_price_minor: listing.unit_price_minor,
      status: listing.status === 'suspended' ? 'paused' : listing.status,
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  cancelEdit(): void {
    this.editingListingId.set('');
    this.listingForm.reset({
      category: this.categories()[0]?.id ?? '',
      name: '',
      description: '',
      unit_code: 'kg',
      unit_price_minor: 1,
      status: 'draft',
    });
  }

  moveStock(event: SubmitEvent, listingId: string): void {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const submitter = event.submitter as HTMLButtonElement | null;
    const data = new FormData(form);
    const batch = String(data.get(`batch-${listingId}`) ?? '');
    const quantity = String(data.get(`quantity-${listingId}`) ?? '');
    if (!batch || !quantity || this.movingListingId()) {
      return;
    }
    const action = submitter?.value === 'deallocate' ? 'deallocate' : 'allocate';
    const operationKey = `${action}:${listingId}:${batch}:${quantity}`;
    const requestId =
      this.stockOperationIds()[operationKey] ??
      (crypto.randomUUID());
    this.stockOperationIds.update((ids) => ({ ...ids, [operationKey]: requestId }));
    this.movingListingId.set(listingId);
    this.message.set('');
    this.errorMessage.set('');
    const operation = action === 'allocate'
      ? this.api.allocate(listingId, batch, quantity, requestId)
      : this.api.deallocate(listingId, batch, quantity, requestId);
    operation.subscribe({
      next: () => {
        this.message.set(action === 'allocate' ? 'Stock allocated to listing.' : 'Unreserved stock returned to the batch pool.');
        this.stockOperationIds.update((ids) => {
          const next = { ...ids };
          delete next[operationKey];
          return next;
        });
        this.movingListingId.set('');
        this.load();
      },
      error: (error: unknown) => {
        this.errorMessage.set(this.describeError(error, 'Stock movement failed. Retry using the same operation only if its result is unknown.'));
        this.movingListingId.set('');
      },
    });
  }

  stockFor(id: string): ListingStock | undefined {
    return this.stocks()[id];
  }

  acceptedBatchesFor(listing: Listing): HarvestBatch[] {
    return this.batches().filter(
      (batch) =>
        batch.status === 'accepted' &&
        batch.category === listing.category &&
        batch.unit_code === listing.unit_code,
    );
  }

  categoryName(id: string): string {
    return this.categories().find((category) => category.id === id)?.name ?? 'Crop';
  }

  private describeError(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse && error.status === 0) {
      return 'Could not reach the API. Check the backend and exact CORS origin configuration.';
    }
    if (error instanceof HttpErrorResponse && error.status === 403) {
      return 'The API denied this action for the current account.';
    }
    if (error instanceof HttpErrorResponse && error.status === 409) {
      return 'The request conflicts with current stock or record state. Refresh and review the current values.';
    }
    return fallback;
  }
}
