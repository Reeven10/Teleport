import { expect, test } from '@playwright/test';

test('dashboard loads live device stats on mock data', async ({ page }) => {
  await page.goto('/');

  // 1. Verify Shell and Title
  await expect(page.getByText('Teleport', { exact: true })).toBeVisible();

  // 2. Verify SIMULATED Badge
  await expect(page.getByTestId('badge-simulated')).toBeVisible();

  // 3. Verify Device Cards for Device A and Device B
  await expect(page.getByTestId('device-card-device-a')).toBeVisible();
  await expect(page.getByTestId('device-card-device-b')).toBeVisible();

  // 4. Verify Link Card
  await expect(page.getByText('Peer Transport')).toBeVisible();

  // 5. Navigate to Workloads page
  await page.getByRole('link', { name: /Workloads/i }).click();
  await expect(page.getByText('Workload Registry & Feasibility')).toBeVisible();
  await expect(page.getByTestId('workload-card-wl-token-trainer')).toBeVisible();
});
