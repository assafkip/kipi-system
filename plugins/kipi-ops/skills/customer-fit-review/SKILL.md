---
name: customer-fit-review
description: "Run expert persona reviews against generated output anchored to customer deployment reality."
---

# Customer Fit Review

## Purpose
Run expert persona reviews against any generated output, anchored to the customer's actual deployment reality. Catches technically correct but operationally wrong output before it reaches the customer.

## When to Use
Invoke when:
- Generated output (reports, configs, rules, policies, code) is ready for customer delivery
- A demo, POC, or pilot package needs validation
- User says "review for [customer]", "customer fit check", "validate output for [name]"
- After any automated generation pipeline completes

## What This Is NOT
This is not a code review. It does not check whether the code compiles or the tests pass. Those are CI gates. This checks whether the OUTPUT fits the CUSTOMER -- whether it assumes infrastructure they don't have, defaults that would break their environment, or expertise they don't possess.

---

## Input Required

### 1. Output Files
The files to review. Can be any format: configs, scripts, reports, policies, CSVs, markdown, JSON.

### 2. Customer Profile
A structured profile with deployment reality fields. **Reviews without this profile are prohibited.** The SJI Fire incident proved that expert reviews without customer context produce technically correct but operationally wrong results (approved a policy that would have locked out firefighters, assumed infrastructure that didn't exist, claimed coverage on devices with no agent).

```yaml
customer_profile:
  # Identity
  name: ""
  sector: ""                    # fire_department, healthcare, financial, saas, etc.
  employee_count: 0
  security_team_size: 0         # 0 = solo operator

  # Deployment Reality
  managed_device_count: 0       # devices with your agent/tool installed
  unmanaged_device_count: 0     # BYOD, personal devices, contractor machines
  byod_policy: ""               # allowed, restricted, blocked
  licensing_tier: ""            # what tier of your product/platform they have
  infrastructure_present:       # what they ACTUALLY have running
    - ""
  infrastructure_absent:        # what they DON'T have (common assumptions that are wrong)
    - ""
  integrations_configured:      # what's actually connected and sending data
    - ""
  integrations_not_configured:  # known gaps in their setup
    - ""

  # Context
  compliance_frameworks: []     # derived from sector
  prior_incidents: []           # relevant history
  contact_background: ""        # their expertise level
  contact_constraints: ""       # time, budget, team size limitations
  primary_risk_surface: ""      # where attacks most likely enter their environment
```

---

## Execution

### Wave 1: Profile Validation
Before any reviews, validate the customer profile is complete. If any deployment reality field is empty, STOP and ask. Do not review with assumptions.

### Wave 2: Persona Reviews (Parallel)
Spawn one agent per persona. Each agent receives:
- The output files relevant to their domain
- The full customer profile
- The task: "Review this output for [customer name]. They have [X employees], [Y managed devices], [Z unmanaged devices], [licensing tier], [infrastructure present/absent]. Evaluate whether this output helps THIS SPECIFIC customer, not a generic enterprise."

### Wave 3: Fix Pass (Sequential)
Collect all findings. Apply fixes. Re-validate affected files.

---

## Persona Definitions

### Shared Review Criteria (All Personas)

Every persona checks:
1. **Format correctness** - Right file format for the platform?
2. **Syntactic validity** - Would this parse/import without errors?
3. **Customer actionability** - Can THIS CUSTOMER use this without rewriting?
4. **False positive risk** - Would this create noise in an org of THIS SIZE?
5. **Infrastructure fit** - Does this assume services/licensing the customer actually has?
6. **Coverage honesty** - Do claims account for unmanaged devices and unconfigured integrations?
7. **Response guidance** - Does every detection/alert include what to do when it fires?
8. **Triage gates** - Does every prerequisite-dependent output include a "does this apply to you?" check?
9. **Provenance** - Can the customer trace this back to a source?
10. **Plain language** - Could the customer's contact person understand and act on this?

### Deviation Rules (Auto-Applied)

These trigger automatically during review. The persona STOPS and flags:

1. **Infrastructure assumption** - Output assumes a service, license, or integration the customer doesn't have. Flag it. Add a triage gate or skip the output.
2. **Dangerous default** - Output would break the customer's environment (lock out users, delete data, block legitimate access). Flag it. Adjust to safe defaults.
3. **Coverage lie** - Output claims "all devices" or "fully covered" when coverage is partial (unmanaged devices, unconfigured integrations). Flag it. Qualify the claim.
4. **Expertise assumption** - Output requires knowledge the customer's contact doesn't have, with no explanation or portal path. Flag it. Add plain-language guidance.

### Persona List

Personas are domain-specific. Define them based on the output being reviewed. Common set:

**Domain Expert Personas (technical review with customer context):**
- One persona per major output domain (e.g., detection rules, identity policies, compliance, infrastructure configs)
- Each persona is an expert in that domain who has worked with small/resource-constrained organizations
- Each reviews for technical correctness AND customer fit simultaneously

**The Customer Persona (non-negotiable, always included):**
- Constructed from the customer profile's contact_background and contact_constraints
- Reviews AS the customer, not FOR the customer
- Asks: "Can I do this with my resources? Do I know what to do if something goes wrong? Does this make me feel stupid? Would I pay for this?"
- This persona's "would use" verdict is the ultimate gate

### Persona Output Format

```markdown
## [Persona Name] Review
Pass/Fail: [PASS | FAIL | PASS WITH NOTES]
Customer-fit: [Does this help THIS SPECIFIC customer?]
Issues: [numbered list with severity]
Fixes: [numbered list with specific file/line changes]
Confidence: [Would deploy as-is | Needs minor edits | Needs rework]
```

---

## Output

```
[output-dir]/
  persona-reviews.md          # All reviews with scorecard
  customer_profile.yaml       # Profile used for reviews
  fixes-applied.md            # List of fixes applied after reviews
```

## Completion Gate

- [ ] All domain expert personas pass (PASS or PASS WITH NOTES)
- [ ] Customer persona says "would use"
- [ ] No deviation rule was triggered without resolution
- [ ] No output assumes infrastructure the customer doesn't have without a triage gate
- [ ] No output would break the customer's environment with current defaults
- [ ] Every finding is either fixed or documented as a known limitation
