import { expect, Page, test } from '@playwright/test';

// Playwright starts an isolated, seeded Django API using a temporary SQLite database.
const PASSWORD = 'AgriFi-Demo-2026!';

async function signIn(page: Page, email: string) {
  await page.goto('/login');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/localhost:4201\/$/);
}

test.describe.configure({ mode: 'serial' });

test('rejects a wrong password with a clear message', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email address').fill('buyer@agrifi.demo');
  await page.getByLabel('Password').fill('not-the-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toContainText('incorrect');
});

test('unauthenticated visitors are sent to login', async ({ page }) => {
  await page.goto('/marketplace');
  await expect(page).toHaveURL(/\/login$/);
});

test('buyer trade lifecycle: order, confirm, simulated payment, ship, deliver, complete', async ({
  browser,
}) => {
  const buyerContext = await browser.newContext();
  const farmerContext = await browser.newContext();
  const buyer = await buyerContext.newPage();
  const farmer = await farmerContext.newPage();

  await signIn(buyer, 'buyer@agrifi.demo');
  await buyer.getByRole('link', { name: 'Marketplace' }).click();
  await expect(buyer.getByRole('heading', { name: 'Browse agricultural offers' })).toBeVisible();
  await buyer.getByPlaceholder('Search crops').fill('Premium white maize');
  await buyer.getByRole('link', { name: 'View offer' }).click();

  await buyer.getByLabel(/Quantity/).fill('2');
  await buyer.getByLabel('Delivery address').fill('12 Allen Avenue, Ikeja, Lagos');
  await buyer.getByRole('button', { name: 'Place order' }).click();
  await expect(buyer).toHaveURL(/\/orders\/[0-9a-f-]{36}$/);
  const orderUrl = buyer.url();
  await expect(buyer.getByText('Order total')).toBeVisible();
  // Angular's en-US currency formatter displays the currency code for NGN.
  // 2 kg x NGN350.00, calculated by the server.
  await expect(buyer.getByText('NGN700.00').first()).toBeVisible();

  await signIn(farmer, 'farmer@agrifi.demo');
  await farmer.goto(orderUrl);
  await farmer.getByRole('button', { name: 'Confirm order' }).click();
  await expect(farmer.getByText('Confirmed').first()).toBeVisible();

  await buyer.reload();
  await buyer.getByRole('button', { name: 'Record simulated payment' }).click();
  await expect(buyer.getByText('No real money moved.')).toBeVisible();

  await farmer.reload();
  await farmer.getByRole('button', { name: 'Mark shipped' }).click();
  await expect(farmer.getByRole('button', { name: 'Mark delivered' })).toBeVisible();
  await farmer.getByRole('button', { name: 'Mark delivered' }).click();

  await buyer.reload();
  await buyer.getByRole('button', { name: 'Confirm delivery' }).click();
  await expect(buyer.getByText('Completed').first()).toBeVisible();

  await buyerContext.close();
  await farmerContext.close();
});

test('operations admin sees review queues; finance operator sees simulated finance', async ({
  browser,
}) => {
  const opsContext = await browser.newContext();
  const ops = await opsContext.newPage();
  await signIn(ops, 'ops@agrifi.demo');
  await ops.getByRole('link', { name: 'Operations' }).click();
  await expect(ops.getByRole('heading', { name: 'Harvest-batch review' })).toBeVisible();
  await expect(ops.getByRole('heading', { name: 'Listing moderation' })).toBeVisible();
  await expect(ops.getByRole('heading', { name: 'Dispute resolution' })).toBeVisible();
  await opsContext.close();

  const financeContext = await browser.newContext();
  const finance = await financeContext.newPage();
  await signIn(finance, 'finance@agrifi.demo');
  await finance.getByRole('link', { name: 'Finance' }).click();
  await expect(finance.getByText(/simulated/i).first()).toBeVisible();
  await financeContext.close();
});

test('farmer workspace lists seeded stock-backed listings', async ({ page }) => {
  await signIn(page, 'farmer2@agrifi.demo');
  await page.getByRole('link', { name: 'Farmer workspace' }).click();
  await expect(
    page.getByRole('heading', { name: 'My listings and available stock' }),
  ).toBeVisible();
  await expect(page.getByText('Parboiled local rice')).toBeVisible();
});
