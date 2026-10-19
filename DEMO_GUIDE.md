# TENANTSHIELD: 3-minute judge walkthrough

**One-line pitch:** TENANTSHIELD doesn't just flag that a tenant boundary is broken. It proves it, saves the proof as a
test, and verifies the fix.

**The problem (15 s):** In a multi-tenant SaaS, one missing ownership check lets College ABC read College XYZ's marksheets.
Normal API tests say "the endpoint returns 200" and call it healthy.

## Live script
1. **Demo Environment**: two colleges, one private document each, mode = *Vulnerable*.
2. **Overview → Run isolation tests**: 3 pass, **2 findings**. Point out the four-step strip: Test → Prove → Preserve → Verify.
3. **Findings → open one**: Alice (ABC) asked for `doc_xyz_001` and got `200` with the document owned by XYZ.
   Expected vs actual side by side; token redacted; no document body stored.
4. **Download evidence report** (shareable markdown). **Save as regression test**.
5. **Demo Environment → Switch to fixed mode**.
6. **Finding page → Run test again**: `404`, **Fixed: retest passed**.
7. **Proof timeline**: failure and fix on one page. Re-enable vulnerable mode and rerun to show the test fails again.

## Likely judge questions
- **How do you avoid false positives?** Verdicts come from explicit assertions on status *and* the returned resource's owner,
  never from an AI. A denial is a pass; `200` alone is not a finding. Unreachable API = *inconclusive*, never "secure".
- **Is the vulnerability real?** Yes: a real endpoint with the ownership check removed, reachable only in an explicit local demo session. The engine calls it through an in-process ASGI client, so it cannot be pointed anywhere else.
- **Can it scan arbitrary sites?** No, by design: there is no target URL setting at all, only the bundled demo, and stored tests are schema-validated before they run.
- **What's new?** Not any single technique (OWASP covers the ideas). The contribution is the combined, repeatable loop in one tool.
- **Limits:** single-user local tool with no authentication (loopback-only by design); one resource type, GET endpoints, two tenants; 5 synthetic cases prove the workflow, not production accuracy.
- **Next:** point it at a user's own staging API via a config file, write/delete checks, CI mode that fails builds on regression.
