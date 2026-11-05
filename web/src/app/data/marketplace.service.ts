import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';
import { environment } from '../../environments/environment';

export interface Listing {
  id: string;
  seller_name: string;
  category: string;
  name: string;
  description: string;
  unit_code: string;
  unit_price_minor: number;
  currency: string;
  status: string;
  available_quantity?: string;
}

export interface ListingInput {
  category: string;
  name: string;
  description: string;
  unit_code: string;
  unit_price_minor: number;
  status: string;
}

export interface CropCategory {
  id: string;
  name: string;
  is_active: boolean;
  slug?: string;
  description?: string;
}

export interface HarvestBatch {
  id: string;
  category: string;
  quantity: string;
  unit_code: string;
  harvested_on: string;
  client_sync_id?: string | null;
  notes: string;
  status: 'submitted' | 'accepted' | 'rejected';
  rejection_reason: string;
  resubmission_of?: string | null;
  correction_id?: string | null;
  created_at: string;
}

export interface ListingStock {
  listing: string;
  unit_code: string;
  on_hand: string;
  reserved: string;
  available: string;
}

export interface OrderSummary {
  id: string;
  buyer: string;
  seller: string;
  status: string;
  currency: string;
  total_minor: number;
  created_at: string;
  delivery_address: string;
  notes: string;
  items: OrderItem[];
  history: OrderHistory[];
}

export interface OrderItem {
  id: string;
  listing: string;
  listing_name: string;
  category_name: string;
  seller_name: string;
  unit_code: string;
  unit_price_minor: number;
  quantity: string;
  line_total_minor: number;
}

export interface OrderHistory {
  from_status: string;
  to_status: string;
  actor: string | null;
  reason: string;
  created_at: string;
}

export interface Dispute {
  id: string;
  order: string;
  opened_by: string;
  reason: string;
  previous_order_status: string;
  status: string;
  outcome: string;
  resolution_notes: string;
  created_at: string;
}

export interface OrderInput {
  client_request_id: string;
  items: Array<{ listing: string; quantity: string }>;
  delivery_address: string;
  notes: string;
}

export interface FinancialRecord {
  id: string;
  order?: string;
  payment?: string;
  buyer?: string;
  seller?: string;
  status: string;
  amount_minor: number;
  currency: string;
  simulation_label: string;
}

export interface LedgerAccount {
  code: string;
  name: string;
  currency: string;
  debit_balance_minor: number;
}

export interface FinanceReportSummary {
  currency: string;
  status?: string;
  kind?: string;
  count: number;
  total_minor: number;
}

export interface FinanceReport {
  simulated: boolean;
  simulation_label: string;
  trial_balance: {
    accounts: {
      code: string;
      name: string;
      currency: string;
      debit_minor: number;
      credit_minor: number;
      net_debit_minor: number;
    }[];
    totals: { currency: string; debit_minor: number; credit_minor: number; balanced: boolean }[];
  };
  journals: FinanceReportSummary[];
  payments: FinanceReportSummary[];
  refunds: FinanceReportSummary[];
  settlements: FinanceReportSummary[];
}

export interface JournalEntry {
  id: string;
  reference: string;
  source_type: string;
  kind: string;
  currency: string;
  debit_total_minor: number;
  credit_total_minor: number;
  memo: string;
  posted_at: string;
}

interface ApiPage<T> {
  results: T[];
}

@Injectable({ providedIn: 'root' })
export class MarketplaceService {
  private readonly apiUrl = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  listings(mine = false): Observable<Listing[]> {
    let params = new HttpParams();
    if (mine) {
      params = params.set('mine', 'true');
    } else {
      params = params.set('status', 'active');
    }
    return this.collection<Listing>(`${this.apiUrl}/listings/`, params);
  }

  operationsListings(): Observable<Listing[]> {
    return this.collection<Listing>(`${this.apiUrl}/listings/`);
  }

  listing(id: string): Observable<Listing> {
    return this.http.get<Listing>(`${this.apiUrl}/listings/${id}/`);
  }

  createListing(payload: ListingInput): Observable<Listing> {
    return this.http.post<Listing>(`${this.apiUrl}/listings/`, payload);
  }

  updateListing(id: string, payload: Partial<ListingInput>): Observable<Listing> {
    return this.http.patch<Listing>(`${this.apiUrl}/listings/${id}/`, payload);
  }

  listingStock(id: string): Observable<ListingStock> {
    return this.http.get<ListingStock>(`${this.apiUrl}/listings/${id}/stock/`);
  }

  allocate(id: string, batch: string, quantity: string, client_request_id: string): Observable<unknown> {
    return this.http.post(`${this.apiUrl}/listings/${id}/allocate/`, {
      batch,
      quantity,
      client_request_id,
    });
  }

  deallocate(id: string, batch: string, quantity: string, client_request_id: string): Observable<unknown> {
    return this.http.post(`${this.apiUrl}/listings/${id}/deallocate/`, {
      batch,
      quantity,
      client_request_id,
    });
  }

  categories(): Observable<CropCategory[]> {
    return this.collection<CropCategory>(`${this.apiUrl}/categories/`);
  }

  createCategory(payload: { name: string; description: string }): Observable<CropCategory> {
    return this.http.post<CropCategory>(`${this.apiUrl}/categories/`, payload);
  }

  updateCategory(id: string, payload: Partial<CropCategory>): Observable<CropCategory> {
    return this.http.patch<CropCategory>(`${this.apiUrl}/categories/${id}/`, payload);
  }

  harvestBatches(): Observable<HarvestBatch[]> {
    return this.collection<HarvestBatch>(`${this.apiUrl}/harvest-batches/`);
  }

  createHarvestBatch(payload: {
    category: string;
    quantity: string;
    unit_code: string;
    harvested_on: string;
    client_sync_id: string;
    notes: string;
    resubmission_of?: string;
  }): Observable<HarvestBatch> {
    return this.http.post<HarvestBatch>(`${this.apiUrl}/harvest-batches/`, payload);
  }

  reviewHarvestBatch(id: string, action: 'accept' | 'reject', reason = ''): Observable<HarvestBatch> {
    return this.http.post<HarvestBatch>(
      `${this.apiUrl}/harvest-batches/${id}/${action}/`,
      action === 'reject' ? { reason } : {},
    );
  }

  orders(): Observable<OrderSummary[]> {
    return this.collection<OrderSummary>(`${this.apiUrl}/orders/`);
  }

  order(id: string): Observable<OrderSummary> {
    return this.http.get<OrderSummary>(`${this.apiUrl}/orders/${id}/`);
  }

  createOrder(payload: OrderInput): Observable<OrderSummary> {
    return this.http.post<OrderSummary>(`${this.apiUrl}/orders/`, payload);
  }

  transitionOrder(id: string, action: string, reason = ''): Observable<OrderSummary> {
    return this.http.post<OrderSummary>(
      `${this.apiUrl}/orders/${id}/${action}/`,
      action === 'cancel' ? { reason } : {},
    );
  }

  openDispute(id: string, reason: string): Observable<Dispute> {
    return this.http.post<Dispute>(`${this.apiUrl}/orders/${id}/dispute/`, { reason });
  }

  disputes(): Observable<Dispute[]> {
    return this.collection<Dispute>(`${this.apiUrl}/disputes/`);
  }

  resolveDispute(
    id: string,
    outcome: 'buyer_favoured' | 'seller_favoured',
    notes: string,
  ): Observable<Dispute> {
    return this.http.post<Dispute>(`${this.apiUrl}/disputes/${id}/resolve/`, { outcome, notes });
  }

  createPayment(order: string, client_request_id: string): Observable<FinancialRecord> {
    return this.http.post<FinancialRecord>(`${this.apiUrl}/simulated-payments/`, {
      order,
      client_request_id,
    });
  }

  createRefund(
    payment: string,
    amount_minor: number,
    reason: string,
    client_request_id: string,
  ): Observable<FinancialRecord> {
    return this.http.post<FinancialRecord>(`${this.apiUrl}/simulated-refunds/`, {
      payment,
      amount_minor,
      reason,
      client_request_id,
    });
  }

  createSettlement(order: string, client_request_id: string): Observable<FinancialRecord> {
    return this.http.post<FinancialRecord>(`${this.apiUrl}/simulated-settlements/`, {
      order,
      client_request_id,
    });
  }

  payments(): Observable<FinancialRecord[]> {
    return this.collection<FinancialRecord>(`${this.apiUrl}/simulated-payments/`);
  }

  refunds(): Observable<FinancialRecord[]> {
    return this.collection<FinancialRecord>(`${this.apiUrl}/simulated-refunds/`);
  }

  settlements(): Observable<FinancialRecord[]> {
    return this.collection<FinancialRecord>(`${this.apiUrl}/simulated-settlements/`);
  }

  ledgerAccounts(): Observable<LedgerAccount[]> {
    return this.collection<LedgerAccount>(`${this.apiUrl}/finance/ledger-accounts/`);
  }

  financeReport(): Observable<FinanceReport> {
    return this.http.get<FinanceReport>(`${this.apiUrl}/finance/reports/`);
  }

  journals(): Observable<JournalEntry[]> {
    return this.collection<JournalEntry>(`${this.apiUrl}/finance/journal-entries/`);
  }

  private collection<T>(url: string, params = new HttpParams()): Observable<T[]> {
    return this.http.get<T[] | ApiPage<T>>(url, { params }).pipe(
      map((response) => (Array.isArray(response) ? response : response.results)),
    );
  }
}
