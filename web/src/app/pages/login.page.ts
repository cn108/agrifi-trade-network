import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../auth/auth.service';

@Component({
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <main class="flex min-h-screen items-center justify-center px-5 py-12">
      <section class="auth-panel grid w-full max-w-5xl overflow-hidden rounded-3xl bg-white shadow-xl md:grid-cols-2">
        <div class="hidden flex-col justify-between bg-emerald-950 p-10 text-white md:flex">
          <a class="text-xl font-bold tracking-tight" routerLink="/">AgriFi</a>
          <div>
            <p class="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-emerald-300">
              Trade with confidence
            </p>
            <h1 class="max-w-sm text-4xl font-semibold leading-tight">
              A clearer path from harvest to market.
            </h1>
            <p class="mt-5 max-w-sm leading-7 text-emerald-100/75">
              Connect with verified agricultural supply and manage your business in one place.
            </p>
          </div>
          <p class="text-xs text-emerald-100/50">Built for Nigeria's agricultural trade network.</p>
        </div>

        <div class="p-7 sm:p-11">
          <a class="text-lg font-bold text-emerald-900 md:hidden" routerLink="/">AgriFi</a>
          <p class="mt-8 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-700 md:mt-0">
            Welcome back
          </p>
          <h2 class="mt-2 text-3xl font-semibold tracking-tight">Sign in to your account</h2>
          <p class="mt-3 text-sm leading-6 text-slate-500">
            Use the account you registered for AgriFi Trade Network.
          </p>

          @if (errorMessage()) {
            <div class="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
                 role="alert">
              {{ errorMessage() }}
            </div>
          }

          <form class="mt-8 space-y-5" [formGroup]="form" (ngSubmit)="submit()">
            <label class="block text-sm font-medium text-slate-700">
              Email address
              <input
                autocomplete="username"
                class="mt-2 block w-full rounded-xl border border-slate-300 px-4 py-3 outline-none transition focus:border-emerald-700 focus:ring-4 focus:ring-emerald-700/10"
                formControlName="email"
                type="email"
              />
            </label>
            <label class="block text-sm font-medium text-slate-700">
              Password
              <input
                autocomplete="current-password"
                class="mt-2 block w-full rounded-xl border border-slate-300 px-4 py-3 outline-none transition focus:border-emerald-700 focus:ring-4 focus:ring-emerald-700/10"
                formControlName="password"
                type="password"
              />
            </label>
            <button
              class="flex w-full items-center justify-center rounded-xl bg-emerald-800 px-4 py-3 font-semibold text-white transition hover:bg-emerald-900 disabled:cursor-not-allowed disabled:opacity-60"
              [disabled]="form.invalid || submitting()"
              type="submit"
            >
              {{ submitting() ? 'Signing in…' : 'Sign in' }}
            </button>
          </form>

          <p class="mt-8 text-xs leading-5 text-slate-500">
            Your session uses a protected refresh cookie. Access tokens are held in memory only.
          </p>
          <p class="mt-5 text-center text-sm text-slate-600">
            New to AgriFi?
            <a class="font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/register">
              Create an account
            </a>
          </p>
        </div>
      </section>
    </main>
  `,
})
export class LoginPage {
  private readonly formBuilder = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly submitting = signal(false);
  readonly errorMessage = signal('');
  readonly form = this.formBuilder.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });

  submit(): void {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }

    this.errorMessage.set('');
    this.submitting.set(true);
    this.auth
      .login(this.form.getRawValue())
      .pipe(finalize(() => this.submitting.set(false)))
      .subscribe({
        next: () => void this.router.navigate(['/']),
        error: (error: unknown) => this.errorMessage.set(this.describeError(error)),
      });
  }

  private describeError(error: unknown): string {
    if (error instanceof HttpErrorResponse && error.status === 401) {
      return 'The email or password is incorrect.';
    }
    if (error instanceof HttpErrorResponse && error.status === 0) {
      return 'Could not reach the AgriFi API. Check that the backend is running and configured for this dashboard origin.';
    }
    if (error instanceof HttpErrorResponse && error.status === 429) {
      return 'Too many sign-in attempts. Wait a minute and try again.';
    }
    return 'Sign-in failed. Please try again.';
  }
}
