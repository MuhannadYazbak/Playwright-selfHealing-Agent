import { test, expect } from '@playwright/test';

test('Frontend Sanity Check', async ({ page }) => {
  // Navigate to your Next.js local server running in the pipeline
  await page.goto('http://localhost:3000');
  
  // Verify the page loaded by checking the title or a basic element
  await expect(page).toHaveTitle(/TechMart|Playwright/i); 
});