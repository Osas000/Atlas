# Atlas

# Opportunity Engine Specification

Version: 1.0

Status:
Core Revenue Subsystem

Depends On

01A_ATLAS_OPERATIONS_CORE.md

02_AI_ARCHITECTURE.md

03_MISSION_CONTROL.md

05_BROWSER_COMPANION.md

06_MEMORY_ENGINE.md

---

# Purpose

The Opportunity Engine is responsible for discovering, evaluating, ranking and tracking legitimate professional opportunities.

Its objective is not to show the user more jobs.

Its objective is to identify the highest-value opportunities based on the user's skills, goals, history and available time.

Every recommendation should improve the user's probability of earning income.

---

# Vision

Atlas should become the user's professional opportunity radar.

Instead of manually checking many platforms throughout the day, Atlas continuously monitors supported sources and presents only the most valuable opportunities.

The user should spend time executing work—not endlessly searching for it.

---

# Core Responsibilities

The Opportunity Engine shall:

• Discover opportunities.

• Classify opportunities.

• Remove duplicates.

• Detect scams.

• Score opportunities.

• Match opportunities to user skills.

• Estimate earnings.

• Estimate required effort.

• Estimate probability of success.

• Recommend next actions.

---

# Opportunity Sources

Version One supports:

Freelancing Platforms

• Upwork

• Fiverr

• Freelancer

• Contra

• Outlier

• Alignerr

• Appen

• DataAnnotation

• Toloka

Remote Jobs

• LinkedIn Jobs

• Wellfound

• Remote OK

• We Work Remotely

Future versions may include additional connectors.

---

# Opportunity Lifecycle

Discovered

↓

Validated

↓

Classified

↓

Scored

↓

Ranked

↓

Recommended

↓

Tracked

↓

Completed

↓

Archived

---

# Opportunity Categories

Translation

Coding

AI Evaluation

Data Annotation

Writing

Research

Virtual Assistance

Design

Video Editing

Customer Support

Testing

Microtasks

Remote Employment

Internships

Consulting

Atlas must allow new categories without architectural changes.

---

# Opportunity Object

Each opportunity contains:

Opportunity ID

Platform

Category

Title

Description

Budget

Currency

Deadline

Estimated Duration

Required Skills

Required Experience

Location Restrictions

Application URL

Status

Opportunity Score

Confidence

Risk Level

Discovery Timestamp

---

# Opportunity Scoring

Every opportunity receives a score from 0–100.

Scoring considers:

Expected Earnings

Skill Match

Estimated Completion Time

Competition

Platform Reputation

Client Reputation

Deadline

Acceptance Probability

Career Value

Income Goal Alignment

Learning Value

Long-Term Benefit

The weighting of each factor should be configurable.

---

# Scam Detection

Atlas should identify common warning signs.

Examples include:

Unrealistic earnings.

Requests for upfront payments.

Requests to communicate outside trusted platforms.

Poorly written or suspicious listings.

Known scam patterns.

Low platform trust.

Scam detection should produce a confidence score rather than absolute certainty.

---

# Matching Engine

The engine compares opportunities with:

Skills

Experience

Completed Projects

Proposal History

Success Rate

Learning Goals

Current Availability

Preferred Work Types

The result is a Match Score.

---

# Recommendation Engine

Recommendations are generated using multiple factors.

Example:

Opportunity Score

+

Match Score

+

Current Workload

+

Income Target

+

Deadline

↓

Final Priority

The highest-priority opportunities are surfaced first.

---

# Daily Opportunity Review

Every morning Atlas generates:

New Opportunities

High-Priority Opportunities

Expiring Opportunities

Recommended Applications

Opportunities to Ignore

Reasons for each recommendation must be explained.

---

# Opportunity Tracking

Atlas tracks:

Viewed

Ignored

Applied

Interview Scheduled

Rejected

Accepted

Completed

Paid

Cancelled

This data feeds the Memory Engine and Analytics Engine.

---

# Learning Loop

The Opportunity Engine learns from outcomes.

Examples:

Accepted applications.

Rejected applications.

Completed projects.

Client ratings.

Payment history.

Time spent.

These outcomes refine future scoring.

---

# Notifications

Atlas notifies the user when:

A high-value opportunity appears.

A deadline approaches.

An application status changes.

A client responds.

A payment is confirmed.

Low-value notifications should be batched.

---

# Integration

The Opportunity Engine exchanges information with:

Mission Control

Operations Core

Memory Engine

Analytics Engine

Browser Companion

AI Router

Notification Engine

---

# Performance Requirements

Opportunity ranking should be responsive.

Duplicate detection should be automatic.

Background monitoring should not interrupt active work.

Recommendations should update dynamically.

---

# Security

Atlas must never submit applications automatically without explicit user approval.

User credentials remain under user control.

Sensitive platform information is encrypted where appropriate.

---

# Error Handling

If a platform connector fails:

Retry automatically.

Log the issue.

Continue monitoring other platforms.

Notify the user only if manual intervention is required.

---

# Future Expansion

Future capabilities include:

Market trend analysis.

Salary forecasting.

Competition prediction.

Skill-gap recommendations.

Opportunity clustering.

Cross-platform duplicate detection.

AI-assisted platform discovery.

---

# Acceptance Criteria

The Opportunity Engine succeeds when:

Relevant opportunities are discovered.

Opportunities are ranked accurately.

Low-quality opportunities are filtered.

Recommendations improve over time.

The user spends less time searching.

Legitimate earning opportunities increase.

---

# Engineering Notes

The Opportunity Engine is not designed to maximize applications.

It is designed to maximize successful outcomes.

Quality always takes precedence over quantity.

Every recommendation should move the user closer to sustainable professional growth.

---

# Closing Statement

The Opportunity Engine transforms Atlas from a passive organizer into an active opportunity discovery platform.

Its success is measured not by the number of jobs displayed, but by the quality of opportunities that lead to meaningful, legitimate professional success.