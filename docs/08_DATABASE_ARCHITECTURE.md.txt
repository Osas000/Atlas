# Atlas

# Database Architecture Specification

Version: 1.0

Status:
Core Infrastructure

Depends On

01A_ATLAS_OPERATIONS_CORE.md

01B_ATLAS_KERNEL.md

05_BROWSER_COMPANION.md

06_MEMORY_ENGINE.md

07_OPPORTUNITY_ENGINE.md

---

# Purpose

The Atlas Database is the permanent source of truth.

Every subsystem stores and retrieves information through the database.

The database must be reliable, consistent, scalable and easy to extend.

No subsystem should own its own isolated data store.

---

# Design Philosophy

Atlas follows one principle.

One source of truth.

Every piece of information exists only once.

Every subsystem references shared data instead of duplicating it.

This minimizes inconsistency and simplifies maintenance.

---

# Database Technology

Version One

SQLite

Reasons

• Local first

• Fast

• Zero configuration

• Reliable

• Easy backup

• Works offline

Future

PostgreSQL

For cloud synchronization and multi-device support.

---

# Database Layers

Storage Layer

↓

Repository Layer

↓

Service Layer

↓

Operations Core

↓

Mission Control

No component should query SQLite directly.

All access passes through repositories.

---

# Core Entities

Atlas contains the following primary entities.

User

Mission

Opportunity

Application

Project

Client

Proposal

Task

Skill

Platform

Memory

Knowledge

Notification

Analytics

Settings

Event

Session

Document

Template

Payment

Review

Each entity has a dedicated repository.

---

# User Table

Stores

Identity

Goals

Working Hours

Income Targets

Skills

Preferences

Experience

Profile Settings

---

# Mission Table

Stores

Mission ID

Objective

Priority

Status

Estimated Income

Current Progress

Creation Date

Completion Date

---

# Opportunity Table

Stores

Platform

Title

Description

Budget

Currency

Deadline

Category

Opportunity Score

Status

Risk Level

Discovery Date

Application URL

---

# Application Table

Tracks

Applied

Interview

Rejected

Accepted

Completed

Cancelled

Proposal Used

Submission Date

Response Date

---

# Client Table

Stores

Client Name

Platform

Ratings

Completed Projects

Average Budget

Communication Notes

Trust Score

History

---

# Proposal Table

Stores

Proposal Content

Version

Template

Outcome

Client

Opportunity

Acceptance Status

Lessons Learned

---

# Project Table

Stores

Project Name

Client

Platform

Status

Deliverables

Files

Deadlines

Notes

Income

Completion Date

---

# Memory Table

Stores

Memory Type

Category

Importance

Relationships

Tags

Summary

Embedding Reference (Future)

---

# Knowledge Table

Stores

Platform Guides

Best Practices

Templates

Research

Documentation

Tutorials

Learning Material

---

# Task Table

Stores

Task

Priority

Deadline

Mission

Status

Estimated Time

Completion Time

Dependencies

---

# Skill Table

Stores

Skill Name

Proficiency

Learning Progress

Projects Using Skill

Last Used

Improvement Suggestions

---

# Notification Table

Stores

Notification Type

Priority

Status

Read State

Timestamp

Related Entity

---

# Analytics Table

Stores

Daily Earnings

Weekly Earnings

Applications

Acceptance Rate

Hours Worked

Productivity

Mission Success

Historical Trends

---

# Event Table

Stores

System Events

Browser Events

Mission Events

Errors

Warnings

Recoveries

Background Tasks

---

# Settings Table

Stores

Theme

Language

Permissions

AI Provider

Notifications

Privacy

Browser Settings

Experimental Features

---

# Relationships

User

↓

Mission

↓

Tasks

↓

Projects

↓

Applications

↓

Clients

↓

Payments

↓

Analytics

Everything is connected through relationships rather than duplication.

---

# Repository Pattern

Every table has a repository.

Example

OpportunityRepository

ClientRepository

MissionRepository

MemoryRepository

AnalyticsRepository

Repositories expose clean methods.

No SQL outside repositories.

---

# Indexing

Create indexes for

Opportunity Score

Status

Deadline

Client

Platform

Mission

Tags

Created Date

Updated Date

Frequently searched fields

---

# Transactions

Critical operations use transactions.

Examples

Submitting application

Completing project

Recording payment

Updating mission

If one step fails

Rollback everything.

---

# Backup Strategy

Automatic Daily Backup

Manual Backup

Versioned Backup

Export Database

Import Database

Backup verification

---

# Migration Strategy

Every schema change receives

Version Number

Migration Script

Rollback Script

Validation

No manual database edits.

---

# Security

Sensitive fields encrypted.

Prepared statements only.

No SQL injection.

Permission validation.

Audit logging.

Secure local storage.

---

# Performance

Indexed queries.

Lazy loading where appropriate.

Background indexing.

Batch writes.

Efficient joins.

Minimal duplication.

---

# Error Handling

Database unavailable

↓

Retry

↓

Restore backup if needed

↓

Notify user

↓

Continue safely

Never silently lose data.

---

# Future Expansion

PostgreSQL

Cloud Sync

Knowledge Graph

Vector Database

Shared Workspaces

Multiple Profiles

Encrypted Cloud Backup

---

# Acceptance Criteria

The database succeeds when

Data remains consistent.

Queries are fast.

Backups are reliable.

Relationships remain valid.

Schema supports future expansion.

No unnecessary duplication exists.

---

# Engineering Principles

The database is Atlas's permanent memory.

Every engineering decision should prioritize

Consistency

Reliability

Extensibility

Performance

Security

Maintainability

---

# Closing Statement

The Atlas Database is the foundation upon which every subsystem depends.

It is designed to preserve knowledge, maintain consistency and support Atlas as it evolves from a personal assistant into a complete professional operations platform.