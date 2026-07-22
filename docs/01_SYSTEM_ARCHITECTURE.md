# Atlas
## System Architecture Specification
Version: 1.0
Status: Core Architecture
Depends On: 00_PROJECT_VISION.md

---

# Architecture Philosophy

Atlas is not a chatbot.

Atlas is an operating system.

Every responsibility is assigned to a specialized subsystem.

The AI model is only one component inside the system.

The operating system itself is responsible for planning, organization,
memory, analytics, workflows, communication, and orchestration.

The result is a modular architecture where individual components can evolve
without affecting the rest of the platform.

---

# High-Level Architecture

                            USER
                              │
                              ▼
                     Atlas Command Center
                              │
                ┌─────────────┼─────────────┐
                │             │             │
                ▼             ▼             ▼
        Workflow Engine   Event Bus   Notification Center
                │
      ┌─────────┼─────────────────────────────────────┐
      │         │          │          │               │
      ▼         ▼          ▼          ▼               ▼

 Opportunity  Execution  Memory   Browser      Intelligence
   Engine      Engine    Engine   Companion       Router

      │         │          │          │               │
      └─────────┴──────────┴──────────┴───────────────┘
                              │
                              ▼
                     Local Database & Files

---

# Core Rule

No subsystem talks directly to another subsystem.

Every communication passes through the Event Bus.

Benefits:

• Loose coupling

• Easier debugging

• Future scalability

• Easy replacement of components

---

# The Atlas Departments

Atlas is internally organized into departments.

Each department owns exactly one responsibility.

Departments never duplicate responsibilities.

---

Department 1

Command Center

Purpose

Main user interface.

Responsibilities

Display today's mission

Display opportunities

Display analytics

Display applications

Display active work

Display notifications

Display earnings

Display learning progress

Never performs business logic.

---

Department 2

Workflow Engine

Purpose

Coordinates every workflow inside Atlas.

Examples

Apply for job

Complete annotation

Review proposal

Analyze opportunity

Translate instructions

Update memory

Everything starts here.

---

Department 3

Opportunity Engine

Mission

Find legitimate earning opportunities.

Responsibilities

Search supported platforms

Rank opportunities

Estimate value

Estimate effort

Estimate acceptance probability

Detect duplicates

Filter low-quality opportunities

Flag suspicious listings

Output

Ranked opportunities.

---

Department 4

Execution Engine

Mission

Help complete work.

Responsibilities

Explain tasks

Draft proposals

Translate instructions

Review work

Summarize documents

Suggest improvements

Generate checklists

Never submits work automatically.

The user remains in control.

---

Department 5

Memory Engine

Mission

Never forget useful information.

Stores

Applications

Projects

Clients

Platforms

Payments

Learning

Skills

Documents

Successful strategies

Failed strategies

Knowledge

Memory grows continuously.

---

Department 6

Browser Companion

Mission

Understand the user's current working context.

Capabilities

Read current page with permission.

Identify platform.

Extract important information.

Detect deadlines.

Highlight important actions.

Provide contextual assistance.

Never monitors without permission.

---

Department 7

Intelligence Router

Mission

Provide reasoning.

Responsibilities

Route AI requests.

Switch providers.

Manage prompts.

Handle retries.

Control context.

Fallback strategy.

Future-proof the architecture.

---

Department 8

Notification Center

Mission

Ensure nothing important is missed.

Examples

New opportunities

Deadlines

Interview reminders

Platform alerts

Qualification deadlines

Daily mission

Weekly review

---

Department 9

Analytics Engine

Mission

Measure everything.

Tracks

Applications

Acceptance rate

Income

Hours worked

Estimated hourly earnings

Time saved

Learning progress

Platform performance

Client statistics

Growth trends

---

Department 10

Knowledge Engine

Mission

Build Atlas' internal encyclopedia.

Contains

Platform guides

Qualification notes

Proposal templates

Career advice

Personal notes

Common mistakes

Learning resources

Internal documentation

Avoids repeating AI requests.

---

# Data Flow Example

Scenario

User opens an Upwork job.

1. Browser Companion detects supported platform.
2. Page information is extracted.
3. Event sent to Event Bus.
4. Opportunity Engine scores the job.
5. Memory Engine checks for similar work.
6. Intelligence Router is called only if reasoning is required.
7. Execution Engine prepares recommendations.
8. Command Center presents results.

The user reviews and decides.

---

# AI Usage Policy

AI is invoked only when necessary.

Examples requiring AI

Proposal drafting

Complex translation

Opportunity comparison

Instruction explanation

Research

Review

Examples not requiring AI

Dashboards

Tracking

Notifications

Database operations

Statistics

Scheduling

Application history

Configuration

---

# Memory Hierarchy

Layer 1

Runtime Memory

Temporary session context.

Layer 2

Working Memory

Current projects.

Current applications.

Current tasks.

Layer 3

Long-Term Memory

Everything useful learned over time.

Layer 4

Knowledge Base

Permanent reference information.

---

# Guiding Rule

Before calling AI:

Search Memory.

If found

Return answer.

If not found

Search Knowledge Base.

If found

Return answer.

If still not found

Call Intelligence Router.

This minimizes dependence on AI.

---

# Failure Strategy

If AI is unavailable

Atlas continues operating.

Dashboards remain available.

Memory remains available.

Analytics remain available.

Tracking remains available.

Only AI-dependent features pause gracefully.

---

# Version One Success Criteria

Atlas is considered successful when it can:

✓ Organize freelance work from one dashboard.

✓ Track opportunities.

✓ Track applications.

✓ Help understand tasks.

✓ Draft quality proposals.

✓ Maintain persistent memory.

✓ Learn from outcomes.

✓ Assist without overwhelming the user.

---

# Architectural Motto

Atlas is not an AI with software attached.

Atlas is software that intelligently uses AI.

This distinction guides every engineering decision.
