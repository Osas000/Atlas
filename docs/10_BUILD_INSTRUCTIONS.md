# Atlas

# Build Instructions

Version: 1.0

Status:
Engineering Build Guide

Audience:
OpenCode AI Engineer

---

# Mission

Your responsibility is to build Atlas into a production-quality desktop application.

Atlas is not a chatbot.

Atlas is an AI-powered Personal Operations Platform that helps a professional discover work, execute work, learn continuously and increase legitimate earnings.

You are expected to build maintainable software rather than generate code quickly.

Quality is always more important than speed.

---

# Engineering Principles

Every engineering decision must optimize for

• Simplicity

• Reliability

• Maintainability

• Extensibility

• Performance

• Security

• User Privacy

If two solutions solve the same problem, choose the simpler one.

---

# Version One Goals

Version One is intentionally limited.

The objective is NOT to build every planned feature.

The objective is to build a stable foundation.

Version One must feel complete even if many future features remain unimplemented.

---

# Technology Stack

Desktop

Electron

Frontend

React

Language

TypeScript

Build Tool

Vite

Styling

Tailwind CSS

Component Library

shadcn/ui

Icons

Lucide React

State Management

Zustand

Database

SQLite

ORM

Drizzle ORM

Validation

Zod

Logging

Pino

Testing

Vitest

End-to-End Testing

Playwright

Package Manager

pnpm

---

# Folder Structure

src/

app/

kernel/

operations/

ai/

departments/

browser/

memory/

database/

analytics/

notifications/

components/

layouts/

pages/

hooks/

services/

repositories/

types/

utils/

styles/

assets/

tests/

Each directory must have a single responsibility.

---

# Coding Standards

Strict TypeScript.

No "any".

Prefer interfaces.

Small reusable functions.

Descriptive variable names.

Meaningful comments.

Avoid duplicated logic.

Prefer composition over inheritance.

No deeply nested components.

---

# Architecture Rules

Never allow the UI to access the database directly.

Never allow components to contain business logic.

Never allow AI providers to communicate directly with browser extensions.

Never duplicate data.

Always use repositories.

Always use services.

All major communication must flow through the Operations Core.

---

# Development Process

Every feature follows the same lifecycle.

Design

↓

Implement

↓

Test

↓

Review

↓

Document

↓

Merge

↓

Continue

Never skip testing.

---

# Milestone One

Project Initialization

Deliverables

Electron

React

TypeScript

Tailwind

SQLite

Drizzle

Logging

Configuration

Theme

Settings

Result

Atlas launches successfully.

---

# Milestone Two

Kernel

Deliverables

Kernel

Startup Sequence

Service Registry

Shutdown Sequence

Configuration Loading

Result

Atlas starts and stops cleanly.

---

# Milestone Three

Operations Core

Deliverables

Event Bus

Workflow Manager

Mission Manager

Priority Engine

Background Scheduler

Result

Core runtime operational.

---

# Milestone Four

Mission Control

Deliverables

Dashboard

Mission Card

Status Bar

Navigation

Quick Actions

Result

User can interact with Atlas.

---

# Milestone Five

Database

Deliverables

Schema

Repositories

Migration System

Backup

Restore

Result

Persistent storage operational.

---

# Milestone Six

Memory Engine

Deliverables

Working Memory

Session Memory

Project Memory

Long-Term Memory

Search

Result

Atlas remembers work.

---

# Milestone Seven

Opportunity Engine

Deliverables

Opportunity Objects

Ranking

Filtering

Tracking

Recommendation

Result

Atlas organizes opportunities.

---

# Milestone Eight

Browser Companion

Deliverables

Extension

Messaging

Platform Detection

Context Extraction

Permissions

Result

Atlas understands supported pages.

---

# Milestone Nine

AI Layer

Deliverables

Provider Router

Prompt Builder

Context Builder

Response Validator

Specialists

Result

AI assistance operational.

---

# Milestone Ten

Productivity Tools

Deliverables

Proposal Assistant

Translation Assistant

Research Assistant

Coding Assistant

Task Assistant

Result

Atlas actively assists work.

---

# UI Rules

Every page must answer

What should I do?

Why?

How much is it worth?

What happens next?

Avoid unnecessary animations.

Professional appearance only.

---

# Error Handling

Every error must

Be logged.

Be recoverable.

Provide useful feedback.

Never expose stack traces to users.

Never crash Atlas because one subsystem fails.

---

# Performance Targets

Cold startup under 5 seconds.

Page switching under 200ms.

Search under 100ms.

Memory retrieval under 150ms.

Background tasks must not block the UI.

---

# Security

Encrypt sensitive data.

Never store secrets in plain text.

Validate every input.

Use parameterized database queries.

Respect browser permissions.

No hidden data collection.

---

# Documentation

Every module must contain

README.md

Purpose

Responsibilities

Dependencies

Public API

Examples

Maintenance Notes

---

# Git Standards

Meaningful commits.

Feature branches.

Pull requests.

No direct commits to main.

---

# Code Quality

Every completed milestone must

Compile successfully.

Pass tests.

Have no TypeScript errors.

Have no ESLint errors.

Be documented.

Remain functional.

---

# Definition of Done

A milestone is complete only if

The feature works.

Tests pass.

Documentation is updated.

Performance remains acceptable.

Existing functionality is not broken.

---

# Engineering Mindset

Atlas is expected to evolve for years.

Never optimize for short-term convenience at the expense of long-term maintainability.

Write code that future engineers can understand.

Every module should be replaceable.

Every subsystem should be independently testable.

---

# Final Instruction

Do not attempt to build Atlas in a single implementation.

Build milestone by milestone.

Verify stability after every milestone.

Atlas should grow incrementally into a reliable professional platform.

Always prioritize quality over speed.

---

# Closing Statement

Atlas is not an experiment.

It is a professional software platform.

Every engineering decision should move Atlas toward becoming a dependable operational partner that users can trust every day.