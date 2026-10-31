import { expect, test } from '@playwright/test';

test.describe('Teleport Dashboard & Migration Scenarios', () => {
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
    await expect(page.getByText('Peer Transport', { exact: true })).toBeVisible();

    // 5. Navigate to Workloads page
    await page.getByRole('link', { name: /Workloads/i }).click();
    await expect(page.getByText('Workload Registry & Feasibility')).toBeVisible();
    await expect(page.getByTestId('workload-card-wl-token-trainer')).toBeVisible();
  });

  test('scenario 1: migration in-flight with 5 of 10 checkpoints and authority on Device A', async ({
    page,
  }) => {
    await page.goto('/migration?scenario=in_flight');

    // Verify Migration page title
    await expect(page.getByText('Migration Engine & Authority Cutover')).toBeVisible();

    // Checkpoint grid counter: 5 of 10 validated
    const counter = page.getByTestId('checkpoint-counter');
    await expect(counter).toBeVisible();
    await expect(counter).toContainText('5 of 10');

    // Invariant note visible: authority has NOT moved yet
    const invariantNote = page.getByTestId('authority-invariant-note');
    await expect(invariantNote).toBeVisible();
    await expect(invariantNote).toContainText('Authority has not moved yet');

    // Authority Panel shows epoch and SOURCE on Device A
    const epochBadge = page.getByTestId('authority-epoch');
    await expect(epochBadge).toBeVisible();
    await expect(epochBadge).toContainText('Epoch 1');

    const sourceBadge = page.getByTestId('authority-state-source');
    await expect(sourceBadge).toBeVisible();
    await expect(sourceBadge).toContainText('SOURCE');

    // Phase stepper shows TRANSFERRING active
    await expect(page.getByTestId('step-transferring')).toBeVisible();
  });

  test('scenario 2: completed migration cutover with interruption time', async ({
    page,
  }) => {
    await page.goto('/migration?scenario=completed');

    // Verify completed phase badge
    const phaseBadge = page.getByTestId('migration-phase-badge');
    await expect(phaseBadge).toBeVisible();
    await expect(phaseBadge).toContainText('COMPLETED');

    // Interruption time is measured and displayed
    const interruptionTime = page.getByTestId('interruption-time');
    await expect(interruptionTime).toBeVisible();
    await expect(interruptionTime).toContainText('42 ms');

    // Authority moved to Target (Epoch 2)
    const epochBadge = page.getByTestId('authority-epoch');
    await expect(epochBadge).toBeVisible();
    await expect(epochBadge).toContainText('Epoch 2');

    const targetBadge = page.getByTestId('authority-state-target');
    await expect(targetBadge).toBeVisible();
    await expect(targetBadge).toContainText('TARGET');
  });

  test('scenario 3: rollback on checksum mismatch with failure reason', async ({
    page,
  }) => {
    await page.goto('/migration?scenario=rollback');

    // Verify rolled back phase badge
    const phaseBadge = page.getByTestId('migration-phase-badge');
    await expect(phaseBadge).toBeVisible();
    await expect(phaseBadge).toContainText('ROLLED_BACK');

    // Verify failure reason is displayed prominently
    await expect(
      page.getByText(/Validation failed at Checkpoint 4/i)
    ).toBeVisible();

    // Authority stayed safely on SOURCE
    const sourceBadge = page.getByTestId('authority-state-source');
    await expect(sourceBadge).toBeVisible();
    await expect(sourceBadge).toContainText('SOURCE');
  });

  test('scenario 4: remote access viewport and host controls', async ({ page }) => {
    await page.goto('/remote?scenario=remote_access');

    // Verify Remote page header
    await expect(page.getByText('Remote Access Viewport')).toBeVisible();

    // Viewport canvas is mounted
    const canvas = page.getByTestId('remote-viewport-canvas');
    await expect(canvas).toBeVisible();

    // Status bar metrics
    await expect(page.getByTestId('remote-status-bar')).toBeVisible();
    await expect(page.getByTestId('remote-fps')).toBeVisible();
    await expect(page.getByTestId('remote-latency')).toBeVisible();
    await expect(page.getByTestId('remote-link-type')).toBeVisible();

    // Interactive input capture toggle
    await page.getByTestId('btn-capture-controls').click();
    await expect(page.getByTestId('controls-captured-indicator')).toBeVisible();

    // Release controls via button
    await page.getByTestId('btn-release-controls').click();
    await expect(page.getByTestId('btn-capture-controls')).toBeVisible();

    // Simulate host consent modal
    await page.getByTestId('btn-trigger-consent-modal').click();
    const consentModal = page.getByTestId('consent-modal');
    await expect(consentModal).toBeVisible();
    await expect(page.getByText('Remote Control Permission Request')).toBeVisible();

    // Allow consent closes modal
    await page.getByTestId('btn-consent-allow').click();
    await expect(consentModal).not.toBeVisible();
  });
});
