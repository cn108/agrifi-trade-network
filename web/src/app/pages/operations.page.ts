import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import {
  CropCategory,
  Dispute,
  HarvestBatch,
  Listing,
  MarketplaceService,
} from '../data/marketplace.service';

@Component({
  imports: [DatePipe, ReactiveFormsModule, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-7xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/">← Dashboard</a>
      <div class="mt-6">
        <p class="text-sm font-semibold text-emerald-700">Operations administration</p>
        <h1 class="mt-1 text-3xl font-semibold tracking-tight text-slate-900">Review and manage the marketplace</h1>
        <p class="mt-2 text-sm text-slate-500">Operations actions are checked again by the API; finance-only permissions remain separate.</p>
      </div>
      @if (message()) {
        <p class="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">{{ message() }}</p>
      }
      @if (errorMessage()) {
        <p class="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{{ errorMessage() }}</p>
      }
      @if (loading()) {
        <p class="mt-8 rounded-2xl bg-white p-8 text-slate-500">Loading operations queue…</p>
      } @else {
        <section class="mt-8 grid gap-6 xl:grid-cols-2">
          <div class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Crop categories</h2>
            <form class="mt-4 grid gap-3 sm:grid-cols-[1fr_1.5fr_auto]" [formGroup]="categoryForm" (ngSubmit)="createCategory()">
              <input class="form-input mt-0" formControlName="name" maxlength="100" placeholder="Category name" />
              <input class="form-input mt-0" formControlName="description" placeholder="Description (optional)" />
              <button class="action-button" [disabled]="categoryForm.invalid || workingId() === 'category'">Add</button>
            </form>
            <div class="mt-5 divide-y divide-slate-100">
              @for (category of categories(); track category.id) {
                <div class="flex items-center justify-between gap-3 py-3">
                  <div><p class="font-medium text-slate-800">{{ category.name }}</p><p class="text-xs text-slate-500">{{ category.slug }}</p></div>
                  <button class="secondary-button" [disabled]="workingId() === category.id"
                    (click)="toggleCategory(category)">
                    {{ category.is_active ? 'Deactivate' : 'Reactivate' }}
                  </button>
                </div>
              }
              @if (!categories().length) { <p class="py-4 text-sm text-slate-500">No crop categories.</p> }
            </div>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Harvest-batch review</h2>
            <p class="mt-1 text-sm text-slate-500">Accepting a submitted batch records its physical quantity into the stock ledger.</p>
            <div class="mt-4 divide-y divide-slate-100">
              @for (batch of submittedBatches(); track batch.id) {
                <article class="py-4">
                  <div class="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p class="font-semibold text-slate-900">{{ categoryName(batch.category) }} · {{ batch.quantity }} {{ batch.unit_code }}</p>
                      <p class="mt-1 text-xs text-slate-500">Farmer batch {{ batch.id.slice(0, 8) }} · {{ batch.harvested_on | date: 'mediumDate' }}</p>
                      @if (batch.notes) { <p class="mt-2 text-sm text-slate-600">{{ batch.notes }}</p> }
                    </div>
                    <div class="flex gap-2">
                      <button class="action-button" [disabled]="workingId() === batch.id" (click)="reviewBatch(batch, 'accept')">Accept</button>
                      <button class="danger-button" [disabled]="workingId() === batch.id" (click)="reviewBatch(batch, 'reject', rejectReason.value)">Reject</button>
                    </div>
                  </div>
                  <input #rejectReason class="form-input bg-white" placeholder="Reason required to reject" />
                </article>
              }
              @if (!submittedBatches().length) { <p class="py-4 text-sm text-slate-500">No submitted batches awaiting review.</p> }
            </div>
          </div>
        </section>

        <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
          <h2 class="text-lg font-semibold text-slate-900">Listing moderation</h2>
          <div class="mt-4 grid gap-3 md:grid-cols-2">
            @for (listing of listings(); track listing.id) {
              <article class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4">
                <div>
                  <p class="font-semibold text-slate-900">{{ listing.name }}</p>
                  <p class="mt-1 text-xs text-slate-500">{{ listing.seller_name }} · {{ categoryName(listing.category) }} · {{ listing.status }}</p>
                </div>
                <div class="flex gap-2">
                  @if (listing.status !== 'suspended') {
                    <button class="danger-button" [disabled]="workingId() === listing.id" (click)="setListingStatus(listing, 'suspended')">Suspend</button>
                  }
                  @if (listing.status !== 'archived') {
                    <button class="secondary-button" [disabled]="workingId() === listing.id" (click)="setListingStatus(listing, 'archived')">Archive</button>
                  }
                </div>
              </article>
            }
            @if (!listings().length) { <p class="text-sm text-slate-500">No listings found.</p> }
          </div>
        </section>

        <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
          <h2 class="text-lg font-semibold text-slate-900">Dispute resolution</h2>
          <div class="mt-4 grid gap-4 lg:grid-cols-2">
            @for (dispute of openDisputes(); track dispute.id) {
              <article class="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="font-semibold text-slate-900">Order {{ dispute.order.slice(0, 8) }}</p>
                  <a class="text-sm font-semibold text-emerald-800" [routerLink]="['/orders', dispute.order]">Open order</a>
                </div>
                <p class="mt-2 text-sm text-slate-700">{{ dispute.reason }}</p>
                <input #resolutionNotes class="form-input mt-3 bg-white" placeholder="Resolution notes" />
                <div class="mt-3 flex flex-wrap gap-2">
                  <button class="action-button" [disabled]="workingId() === dispute.id" (click)="resolve(dispute, 'buyer_favoured', resolutionNotes.value)">Resolve for buyer</button>
                  <button class="secondary-button" [disabled]="workingId() === dispute.id" (click)="resolve(dispute, 'seller_favoured', resolutionNotes.value)">Resolve for seller</button>
                </div>
              </article>
            }
            @if (!openDisputes().length) { <p class="text-sm text-slate-500">No open disputes.</p> }
          </div>
        </section>
      }
    </main>
  `,
  styles: [`
    .form-input { display: block; width: 100%; margin-top: 0.5rem; border: 1px solid #cbd5e1; border-radius: 0.75rem; background: white; padding: 0.7rem 0.9rem; outline: none; font-size: 0.875rem; }
    .action-button,.secondary-button,.danger-button { border-radius: 0.7rem; padding: 0.6rem 0.8rem; font-size: 0.8rem; font-weight: 600; }
    .action-button { background: #065f46; color: white; }
    .secondary-button { border: 1px solid #cbd5e1; color: #334155; }
    .danger-button { background: #991b1b; color: white; }
    button:disabled { opacity: 0.55; }
  `],
})
export class OperationsPage implements OnInit {
  private readonly api = inject(MarketplaceService);
  readonly categories = signal<CropCategory[]>([]);
  readonly batches = signal<HarvestBatch[]>([]);
  readonly listings = signal<Listing[]>([]);
  readonly disputes = signal<Dispute[]>([]);
  readonly loading = signal(true);
  readonly workingId = signal('');
  readonly message = signal('');
  readonly errorMessage = signal('');
  readonly categoryForm = inject(FormBuilder).nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(100)]],
    description: ['', Validators.maxLength(2000)],
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    forkJoin({
      categories: this.api.categories(),
      batches: this.api.harvestBatches(),
      listings: this.api.operationsListings(),
      disputes: this.api.disputes(),
    }).subscribe({
      next: (data) => {
        this.categories.set(data.categories);
        this.batches.set(data.batches);
        this.listings.set(data.listings);
        this.disputes.set(data.disputes);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'The API denied operations access to one or more management areas.'
            : 'Operations data could not be loaded.',
        );
        this.loading.set(false);
      },
    });
  }

  submittedBatches(): HarvestBatch[] {
    return this.batches().filter((batch) => batch.status === 'submitted');
  }

  openDisputes(): Dispute[] {
    return this.disputes().filter((dispute) => dispute.status === 'open');
  }

  categoryName(id: string): string {
    return this.categories().find((category) => category.id === id)?.name ?? 'Crop';
  }

  createCategory(): void {
    if (this.categoryForm.invalid) return;
    this.workingId.set('category');
    this.message.set('');
    this.api.createCategory(this.categoryForm.getRawValue()).subscribe({
      next: () => {
        this.message.set('Crop category created.');
        this.categoryForm.reset({ name: '', description: '' });
        this.workingId.set('');
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Category could not be created.'),
    });
  }

  toggleCategory(category: CropCategory): void {
    this.workingId.set(category.id);
    this.message.set('');
    this.api.updateCategory(category.id, { is_active: !category.is_active }).subscribe({
      next: () => {
        this.message.set(category.is_active ? 'Category deactivated.' : 'Category reactivated.');
        this.workingId.set('');
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Category status could not be changed.'),
    });
  }

  reviewBatch(batch: HarvestBatch, action: 'accept' | 'reject', reason = ''): void {
    const normalizedReason = reason.trim();
    if (action === 'reject' && !normalizedReason) {
      this.errorMessage.set('Enter a rejection reason before rejecting this batch.');
      return;
    }
    this.workingId.set(batch.id);
    this.message.set('');
    this.errorMessage.set('');
    this.api.reviewHarvestBatch(batch.id, action, normalizedReason).subscribe({
      next: () => {
        this.message.set(action === 'accept' ? 'Batch accepted and receipt recorded.' : 'Batch rejected.');
        this.workingId.set('');
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Batch review failed. Refresh and check current status.'),
    });
  }

  setListingStatus(listing: Listing, status: 'suspended' | 'archived'): void {
    this.workingId.set(listing.id);
    this.message.set('');
    this.api.updateListing(listing.id, { status }).subscribe({
      next: () => {
        this.message.set(`Listing ${status}.`);
        this.workingId.set('');
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Listing moderation action failed.'),
    });
  }

  resolve(dispute: Dispute, outcome: 'buyer_favoured' | 'seller_favoured', notes: string): void {
    this.workingId.set(dispute.id);
    this.message.set('');
    this.api.resolveDispute(dispute.id, outcome, notes).subscribe({
      next: () => {
        this.message.set('Dispute resolved. Any eligible simulated refund is a separate finance action.');
        this.workingId.set('');
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Dispute resolution failed.'),
    });
  }

  private fail(error: unknown, fallback: string): void {
    this.errorMessage.set(
      error instanceof HttpErrorResponse && error.status === 409
        ? 'The record changed state. Refresh the operations queue and try again.'
        : fallback,
    );
    this.workingId.set('');
  }
}
