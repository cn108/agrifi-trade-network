import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { environment } from '../../environments/environment';

type AccountRole = 'buyer' | 'farmer';

interface RegistrationResponse {
  id: string;
  email: string;
  roles: AccountRole[];
}

@Component({
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <main class="flex min-h-screen items-center justify-center px-5 py-10">
      <section class="auth-panel w-full max-w-2xl rounded-3xl bg-white p-7 shadow-xl sm:p-10">
        <a class="text-lg font-bold text-emerald-900" routerLink="/">AgriFi</a>
        @if (registered()) {
          <div class="mt-8 rounded-2xl border border-emerald-200 bg-emerald-50 p-6">
            <p class="font-semibold text-emerald-950">Your account is ready</p>
            <p class="mt-2 text-sm leading-6 text-emerald-900">
              Sign in with your new account to continue. Administrator and finance roles are assigned
              separately and cannot be selected during public registration.
            </p>
            <a
              class="mt-5 inline-flex rounded-xl bg-emerald-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-900"
              routerLink="/login"
            >
              Go to sign in
            </a>
          </div>
        } @else {
          <p class="mt-8 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-700">
            Join the network
          </p>
          <h1 class="mt-2 text-3xl font-semibold tracking-tight text-slate-900">Create an account</h1>
          <p class="mt-2 text-sm leading-6 text-slate-500">
            Choose a buyer or farmer account. The API controls all role assignment and profile creation.
          </p>

          @if (errorMessage()) {
            <div class="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
              {{ errorMessage() }}
            </div>
          }

          <form class="mt-7 grid gap-5 sm:grid-cols-2" [formGroup]="form" (ngSubmit)="submit()">
            <label class="block text-sm font-medium text-slate-700 sm:col-span-2">
              Account type
              <select
                class="mt-2 block w-full rounded-xl border border-slate-300 bg-white px-4 py-3 outline-none focus:border-emerald-700 focus:ring-4 focus:ring-emerald-700/10"
                formControlName="role"
              >
                <option value="buyer">Buyer</option>
                <option value="farmer">Farmer</option>
              </select>
            </label>

            <label class="block text-sm font-medium text-slate-700">
              First name
              <input class="form-input" autocomplete="given-name" formControlName="first_name" />
            </label>
            <label class="block text-sm font-medium text-slate-700">
              Last name
              <input class="form-input" autocomplete="family-name" formControlName="last_name" />
            </label>
            <label class="block text-sm font-medium text-slate-700 sm:col-span-2">
              Email address
              <input class="form-input" autocomplete="email" formControlName="email" type="email" />
            </label>

            @if (form.controls.role.value === 'farmer') {
              <label class="block text-sm font-medium text-slate-700 sm:col-span-2">
                Farmer display name
                <input class="form-input" autocomplete="organization" formControlName="display_name" />
              </label>
            } @else {
              <label class="block text-sm font-medium text-slate-700 sm:col-span-2">
                Business name
                <input class="form-input" autocomplete="organization" formControlName="business_name" />
              </label>
            }

            <label class="block text-sm font-medium text-slate-700 sm:col-span-2">
              Region <span class="font-normal text-slate-400">(optional)</span>
              <input class="form-input" autocomplete="address-level1" formControlName="region" />
            </label>
            <label class="block text-sm font-medium text-slate-700">
              Password
              <input class="form-input" autocomplete="new-password" formControlName="password" type="password" />
            </label>
            <label class="block text-sm font-medium text-slate-700">
              Confirm password
              <input class="form-input" autocomplete="new-password" formControlName="password_confirm" type="password" />
            </label>

            <button
              class="mt-2 flex w-full items-center justify-center rounded-xl bg-emerald-800 px-4 py-3 font-semibold text-white transition hover:bg-emerald-900 disabled:cursor-not-allowed disabled:opacity-60 sm:col-span-2"
              [disabled]="form.invalid || submitting()"
              type="submit"
            >
              {{ submitting() ? 'Creating account…' : 'Create account' }}
            </button>
          </form>

          <p class="mt-6 text-center text-sm text-slate-600">
            Already registered?
            <a class="font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/login">Sign in</a>
          </p>
        }
      </section>
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
export class RegisterPage implements OnInit {
  private readonly formBuilder = inject(FormBuilder);
  private readonly http = inject(HttpClient);

  readonly submitting = signal(false);
  readonly registered = signal(false);
  readonly errorMessage = signal('');
  readonly form = this.formBuilder.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
    password_confirm: ['', Validators.required],
    first_name: [''],
    last_name: [''],
    role: ['buyer' as AccountRole, Validators.required],
    display_name: [''],
    business_name: [''],
    region: [''],
  });

  ngOnInit(): void {
    this.form.controls.role.valueChanges.subscribe((role) => this.setProfileNameValidator(role));
    this.setProfileNameValidator(this.form.controls.role.value);
  }

  submit(): void {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }

    const form = this.form.getRawValue();
    if (form.password !== form.password_confirm) {
      this.errorMessage.set('Passwords do not match.');
      return;
    }

    const profileFields =
      form.role === 'farmer'
        ? { display_name: form.display_name, region: form.region }
        : { business_name: form.business_name, region: form.region };

    this.errorMessage.set('');
    this.submitting.set(true);
    this.http
      .post<RegistrationResponse>(`${environment.apiBaseUrl}/auth/register/`, {
        email: form.email,
        password: form.password,
        password_confirm: form.password_confirm,
        first_name: form.first_name,
        last_name: form.last_name,
        role: form.role,
        ...profileFields,
      })
      .pipe(finalize(() => this.submitting.set(false)))
      .subscribe({
        next: () => this.registered.set(true),
        error: (error: unknown) => this.errorMessage.set(this.describeError(error)),
      });
  }

  private setProfileNameValidator(role: AccountRole): void {
    const control = role === 'farmer' ? this.form.controls.display_name : this.form.controls.business_name;
    const other = role === 'farmer' ? this.form.controls.business_name : this.form.controls.display_name;
    control.setValidators([Validators.required, Validators.maxLength(role === 'farmer' ? 150 : 200)]);
    other.clearValidators();
    control.updateValueAndValidity({ emitEvent: false });
    other.updateValueAndValidity({ emitEvent: false });
  }

  private describeError(error: unknown): string {
    if (error instanceof HttpErrorResponse && error.status === 0) {
      return 'Could not reach the AgriFi API. Check the backend and dashboard origin configuration.';
    }
    if (error instanceof HttpErrorResponse && error.status === 400) {
      return 'Registration details were not accepted. Check the required fields, password rules and whether the email is already in use.';
    }
    if (error instanceof HttpErrorResponse && error.status === 429) {
      return 'Too many registration attempts. Wait a minute and try again.';
    }
    return 'Registration failed. Please try again.';
  }
}
