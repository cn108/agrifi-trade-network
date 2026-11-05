import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RegisterPage } from './register.page';
import { authInterceptor } from '../auth/auth.interceptor';
import { environment } from '../../environments/environment';

describe('RegisterPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [RegisterPage],
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('submits only the selected buyer profile fields and reports success', () => {
    const fixture = TestBed.createComponent(RegisterPage);
    fixture.detectChanges();
    const page = fixture.componentInstance;

    page.form.patchValue({
      email: 'buyer@example.test',
      password: 'Strong-password-902!',
      password_confirm: 'Strong-password-902!',
      first_name: 'Ada',
      last_name: 'Buyer',
      business_name: 'Northern Produce Ltd',
      region: 'Kaduna',
    });
    page.submit();

    const request = http.expectOne(`${environment.apiBaseUrl}/auth/register/`);
    expect(request.request.body).toEqual({
      email: 'buyer@example.test',
      password: 'Strong-password-902!',
      password_confirm: 'Strong-password-902!',
      first_name: 'Ada',
      last_name: 'Buyer',
      role: 'buyer',
      business_name: 'Northern Produce Ltd',
      region: 'Kaduna',
    });
    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush({ id: 'user-id', email: 'buyer@example.test', roles: ['buyer'] });

    expect(page.registered()).toBe(true);
  });
});
