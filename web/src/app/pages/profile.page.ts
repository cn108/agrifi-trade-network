import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { AuthenticatedUser } from '../auth/auth.models';
import { AuthService } from '../auth/auth.service';
import { environment } from '../../environments/environment';

interface EditableProfile {
  display_name?: string;
  business_name?: string;
  region: string;
  location: string;
  verification_status: string;
}

@Component({
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-4xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/">
        ← Back to dashboard
      </a>
      <div class="mt-6">
        <p class="text-sm font-semibold text-emerald-700">Account settings</p>
        <h1 class="mt-1 text-3xl font-semibold tracking-tight text-slate-900">Your profile</h1>
        <p class="mt-2 text-sm leading-6 text-slate-500">
          Update your contact and business information. Verification status is managed by operations.
        </p>
      </div>

      @if (loading()) {
        <div class="mt-8 rounded-2xl border border-slate-200 bg-white p-8 text-slate-500">
          Loading profile…
        </div>
      } @else if (loadError()) {
        <div class="mt-8 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {{ loadError() }}
        </div>
      } @else {
        <section class="mt-8 rounded-2xl border border-slate-200 bg-white p-6 sm:p-8">
          <div class="mb-6">
            <h2 class="text-lg font-semibold text-slate-900">Personal details</h2>
            <p class="mt-1 text-sm text-slate-500">{{ accountEmail() }}</p>
          </div>
          @if (accountMessage()) {
            <p class="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
              {{ accountMessage() }}
            </p>
          }
          @if (accountError()) {
            <p class="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
              {{ accountError() }}
            </p>
          }
          <form class="grid gap-4 sm:grid-cols-2" [formGroup]="accountForm" (ngSubmit)="saveAccount()">
            <label class="text-sm font-medium text-slate-700">
              First name
              <input class="form-input" autocomplete="given-name" formControlName="first_name" />
            </label>
            <label class="text-sm font-medium text-slate-700">
              Last name
              <input class="form-input" autocomplete="family-name" formControlName="last_name" />
            </label>
            <button
              class="mt-2 rounded-xl bg-emerald-800 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-900 disabled:opacity-60 sm:col-span-2 sm:justify-self-start"
              [disabled]="accountForm.invalid || savingAccount()"
              type="submit"
            >
              {{ savingAccount() ? 'Saving…' : 'Save personal details' }}
            </button>
          </form>
        </section>

        <section class="mt-5 rounded-2xl border border-slate-200 bg-white p-6 sm:p-8">
          <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">
                {{ isFarmer() ? 'Farmer profile' : 'Buyer profile' }}
              </h2>
              <p class="mt-1 text-sm text-slate-500">Profile changes do not change your assigned roles.</p>
            </div>
            <span class="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold capitalize text-amber-900">
              Verification: {{ verificationStatus() }}
            </span>
          </div>
          @if (profileMessage()) {
            <p class="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
              {{ profileMessage() }}
            </p>
          }
          @if (profileError()) {
            <p class="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
              {{ profileError() }}
            </p>
          }
          <form class="grid gap-4 sm:grid-cols-2" [formGroup]="profileForm" (ngSubmit)="saveProfile()">
            <label class="text-sm font-medium text-slate-700 sm:col-span-2">
              {{ isFarmer() ? 'Display name' : 'Business name' }}
              <input class="form-input" formControlName="name" />
            </label>
            <label class="text-sm font-medium text-slate-700">
              Region
              <input class="form-input" autocomplete="address-level1" formControlName="region" />
            </label>
            <label class="text-sm font-medium text-slate-700">
              Location
              <input class="form-input" autocomplete="street-address" formControlName="location" />
            </label>
            <button
              class="mt-2 rounded-xl bg-emerald-800 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-900 disabled:opacity-60 sm:col-span-2 sm:justify-self-start"
              [disabled]="profileForm.invalid || savingProfile()"
              type="submit"
            >
              {{ savingProfile() ? 'Saving…' : 'Save profile' }}
            </button>
          </form>
        </section>
      }
    </main>
  `,
  styles: [`
    .form-input {
      display: block;
      width: 100%;
      margin-top: 0.5rem;
      border: 1px solid #cbd5e1;
      border-radius: 0.75rem;
      background: white;
      padding: 0.75rem 1rem;
      outline: none;
    }

    .form-input:focus {
      border-color: #047857;
      box-shadow: 0 0 0 4px rgb(4 120 87 / 10%);
    }
  `],
})
export class ProfilePage implements OnInit {
  private readonly formBuilder = inject(FormBuilder);
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly authUrl = `${environment.apiBaseUrl}/auth`;

  readonly loading = signal(true);
  readonly savingAccount = signal(false);
  readonly savingProfile = signal(false);
  readonly loadError = signal('');
  readonly accountError = signal('');
  readonly accountMessage = signal('');
  readonly profileError = signal('');
  readonly profileMessage = signal('');
  readonly accountEmail = signal('');
  readonly verificationStatus = signal('unverified');
  readonly accountForm = this.formBuilder.nonNullable.group({
    first_name: ['', Validators.maxLength(150)],
    last_name: ['', Validators.maxLength(150)],
  });
  readonly profileForm = this.formBuilder.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    region: ['', Validators.maxLength(100)],
    location: ['', Validators.maxLength(200)],
  });

  private profile: EditableProfile | null = null;
  private farmer = false;

  ngOnInit(): void {
    const user = this.auth.user();
    this.farmer = user?.roles.includes('farmer') ?? false;
    this.profileForm.controls.name.setValidators([
      Validators.required,
      Validators.maxLength(this.farmer ? 150 : 200),
    ]);
    this.profileForm.controls.name.updateValueAndValidity({ emitEvent: false });
    const profileEndpoint = this.farmer ? 'profiles/farmer/' : 'profiles/buyer/';

    forkJoin({
      user: this.http.get<AuthenticatedUser>(`${this.authUrl}/me/`),
      profile: this.http.get<EditableProfile>(`${this.authUrl}/${profileEndpoint}`),
    }).subscribe({
      next: ({ user: account, profile }) => {
        this.profile = profile;
        this.accountEmail.set(account.email);
        this.accountForm.patchValue({
          first_name: account.first_name,
          last_name: account.last_name,
        });
        this.profileForm.patchValue({
          name: profile.display_name ?? profile.business_name ?? '',
          region: profile.region,
          location: profile.location,
        });
        this.verificationStatus.set(profile.verification_status);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.loadError.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'Your account does not have permission to edit this profile.'
            : 'Profile data could not be loaded. Please try again.',
        );
        this.loading.set(false);
      },
    });
  }

  isFarmer(): boolean {
    return this.farmer;
  }

  saveAccount(): void {
    if (this.accountForm.invalid || this.savingAccount()) {
      return;
    }
    this.accountError.set('');
    this.accountMessage.set('');
    this.savingAccount.set(true);
    this.http
      .patch<AuthenticatedUser>(`${this.authUrl}/me/`, this.accountForm.getRawValue())
      .subscribe({
        next: (user) => {
          this.auth.user.set(user);
          this.accountMessage.set('Personal details saved.');
          this.savingAccount.set(false);
        },
        error: () => {
          this.accountError.set('Personal details could not be saved. Please try again.');
          this.savingAccount.set(false);
        },
      });
  }

  saveProfile(): void {
    if (this.profileForm.invalid || this.savingProfile() || !this.profile) {
      return;
    }

    const { name, region, location } = this.profileForm.getRawValue();
    const nameField = this.farmer ? { display_name: name } : { business_name: name };
    const endpoint = this.farmer ? 'profiles/farmer/' : 'profiles/buyer/';
    this.profileError.set('');
    this.profileMessage.set('');
    this.savingProfile.set(true);
    this.http
      .patch<EditableProfile>(`${this.authUrl}/${endpoint}`, { ...nameField, region, location })
      .subscribe({
        next: (profile) => {
          this.profile = profile;
          this.verificationStatus.set(profile.verification_status);
          this.profileMessage.set('Profile saved. Verification status is unchanged.');
          this.savingProfile.set(false);
        },
        error: () => {
          this.profileError.set('Profile could not be saved. Please try again.');
          this.savingProfile.set(false);
        },
      });
  }
}
