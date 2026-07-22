# Atlas

# Browser Companion Specification

Version: 1.0

Status:
Core Subsystem

Depends On

01A_ATLAS_OPERATIONS_CORE.md

01B_ATLAS_KERNEL.md

02_AI_ARCHITECTURE.md

03_MISSION_CONTROL.md

---

# Purpose

The Browser Companion is Atlas's eyes.

It enables Atlas to understand the user's current work context inside supported websites and provide intelligent, contextual assistance.

The Browser Companion never acts without the user's knowledge or permission.

Its purpose is observation and assistance, not automation beyond what the user explicitly authorizes.

---

# Vision

The Browser Companion transforms Atlas from a separate application into an intelligent professional companion.

Instead of asking the user to repeatedly explain what they are looking at, Atlas understands the current context and provides relevant assistance.

---

# Responsibilities

The Browser Companion shall:

• Detect supported websites.

• Identify the active platform.

• Read page content after permission is granted.

• Extract structured information.

• Detect opportunities.

• Detect deadlines.

• Detect messages.

• Detect application forms.

• Detect project requirements.

• Notify the Operations Core of significant events.

---

# Supported Platforms (Version One)

Freelance Platforms

• Upwork

• Fiverr

• Freelancer

• Contra

• Outlier

• Appen

• Alignerr

• DataAnnotation

• Toloka

• UHRS (where applicable)

Remote Job Platforms

• LinkedIn Jobs

• Indeed

• Wellfound

• Remote OK

• We Work Remotely

General Productivity

• Gmail

• Google Docs

• GitHub

• Notion

Additional platforms can be added through modular connectors.

---

# Architecture

The Browser Companion consists of six modules.

Browser Extension

↓

Page Detector

↓

Context Extractor

↓

Event Generator

↓

Operations Core

↓

Mission Control

Each module has a single responsibility.

---

# Components

## Browser Extension

Responsibilities

• Communicate with Atlas.

• Receive user permissions.

• Read page content.

• Send structured events.

---

## Platform Detector

Responsibilities

Identify

Current website

Platform type

Supported features

Authentication status

Current page type

---

## Context Extractor

Extracts

Job title

Description

Requirements

Deadline

Budget

Language

Client information

Forms

Buttons

Messages

Attachments

The extractor produces structured data only.

---

## Event Generator

Converts browser activity into Atlas events.

Examples

Job opened.

Application started.

New client message.

Interview invitation.

Payment received.

Deadline detected.

Profile incomplete.

New opportunity.

---

## Permission Manager

The Browser Companion must always request explicit user permission before reading page content.

Permissions should be granular.

Examples

Read current page

Read supported websites only

Access browser tabs

Read clipboard (optional)

No permission should be enabled by default.

---

## Communication Layer

Communication with Atlas occurs through secure local messaging.

The Browser Companion never communicates directly with AI providers.

All communication passes through the Operations Core.

---

# Workflow

Example: Opportunity Detection

User opens Upwork.

↓

Platform detected.

↓

Context extracted.

↓

Opportunity scored.

↓

Operations Core notified.

↓

Mission updated.

↓

Recommendation displayed.

---

Example: Translation Task

User opens a task written in another language.

↓

Language detected.

↓

Translation Specialist requested.

↓

Translation generated.

↓

Displayed beside the original text.

The original content is preserved.

---

# Data Model

Each browser event contains

Event ID

Timestamp

Platform

URL

Page Type

Title

Extracted Content

Confidence

Permission Level

Related Workflow

---

# Events

Typical events include

PlatformOpened

OpportunityDetected

ClientMessageReceived

ApplicationStarted

ApplicationSubmitted

InterviewScheduled

DeadlineDetected

PaymentConfirmed

ProfileUpdateRequired

AttachmentDetected

---

# Interfaces

Operations Core

Receives events.

Mission Control

Receives recommendations.

Memory Engine

Stores useful context.

Knowledge Engine

Provides platform guidance.

Notification Engine

Generates alerts.

---

# Security

The Browser Companion must:

Never capture passwords.

Never read unrelated websites.

Never access unsupported domains.

Never transmit sensitive data without permission.

Encrypt local communication where appropriate.

Respect browser permission boundaries.

---

# Performance

Page detection should be immediate.

Context extraction should complete quickly.

Background monitoring must consume minimal resources.

The extension should not noticeably slow down browsing.

---

# Error Handling

If extraction fails

Retry.

If still unsuccessful

Log the issue.

Continue operating.

Never crash the browser.

---

# Future Expansion

Future capabilities may include

Calendar integration

Multi-browser support

Document parsing

OCR for screenshots

Voice interaction

Workspace automation (with explicit approval)

Cross-device synchronization

---

# Acceptance Criteria

The Browser Companion succeeds when

Supported platforms are detected.

Relevant information is extracted accurately.

Events reach the Operations Core.

Mission Control updates correctly.

User privacy is respected.

No noticeable browser slowdown occurs.

---

# Closing Statement

The Browser Companion is Atlas's window into the user's professional workspace.

Its purpose is not surveillance.

Its purpose is intelligent contextual assistance that reduces effort, improves decision-making and increases productivity while respecting user control and privacy.