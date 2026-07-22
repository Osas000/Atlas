# Atlas

# AI Architecture Specification

Version: 1.0

Status:
Core Intelligence Layer

Depends On

00_PROJECT_VISION.md

00A_ATLAS_CONSTITUTION.md

00B_PRODUCT_REQUIREMENTS_DOCUMENT.md

01_SYSTEM_ARCHITECTURE.md

---

# Purpose

This document defines how intelligence operates inside Atlas.

It specifies how AI is selected, when AI is used, how memory interacts with AI, how specialist agents collaborate, and how Atlas delivers consistent, reliable assistance while remaining independent of any single AI provider.

Atlas does not consider an LLM to be the product.

The AI model is one component inside a much larger operating system.

---

# Core Philosophy

Atlas is an intelligent operating system.

Not a chatbot.

Every AI interaction must create measurable value.

Atlas should think before speaking.

Atlas should search before thinking.

Atlas should remember before searching.

---

# Intelligence Hierarchy

Every request follows the same hierarchy.

STEP 1

Understand the request.

↓

STEP 2

Search Memory Engine.

↓

STEP 3

Search Knowledge Engine.

↓

STEP 4

Apply Local Rules.

↓

STEP 5

Determine if AI reasoning is required.

↓

STEP 6

Select Specialist Agent.

↓

STEP 7

Select AI Provider.

↓

STEP 8

Generate Deliverable.

↓

STEP 9

Quality Review.

↓

STEP 10

Store useful knowledge.

---

# AI Usage Policy

AI is expensive.

Reasoning is valuable.

Memory is priceless.

Atlas must minimize unnecessary AI calls.

AI is only used when reasoning provides additional value.

---

# Intelligence Router

Purpose

The Intelligence Router is the central brain responsible for coordinating every AI interaction.

Responsibilities

Receive requests.

Determine request category.

Check memory.

Check knowledge.

Determine AI necessity.

Select specialist.

Select provider.

Build context.

Execute reasoning.

Validate response.

Return structured output.

Update memory.

The Router never performs specialist work.

It coordinates specialists.

---

# AI Provider Layer

Atlas must never depend on one AI provider.

Providers are interchangeable.

Version One

Primary Provider

OpenCode (Nemotron)

Future Providers

GPT

Claude

Gemini

DeepSeek

Qwen

OpenRouter

Local Models

Every provider implements the same interface.

Changing providers must require minimal code changes.

---

# Context Management

Atlas should never send unnecessary information.

Every AI request contains only:

Current task

Relevant memory

Relevant knowledge

Relevant user preferences

Specialist instructions

Expected output format

No unrelated history.

No unnecessary conversation.

---

# Response Format

Every specialist returns structured results.

Never free-form text unless explicitly requested.

Standard structure

Mission Summary

Analysis

Recommendations

Risks

Confidence Level

Next Actions

Memory Updates

Follow-up Suggestions

---

# AI Invocation Rules

AI SHOULD be used for

Proposal writing

Translation

Complex reasoning

Research

Summarization

Code review

Task explanation

Comparison

Strategy

Planning

AI SHOULD NOT be used for

Opening dashboards

Filtering records

Searching local database

Notifications

Scheduling

File management

Statistics

Calculations

Configuration

Tracking

---

# Cost Optimization

Atlas must minimize token usage.

Strategies

Reuse memory.

Cache previous reasoning.

Reuse templates.

Compress context.

Send only relevant information.

Avoid duplicate reasoning.

---

# Memory Before AI

Every request follows this order.

Search Runtime Memory.

↓

Search Working Memory.

↓

Search Long-Term Memory.

↓

Search Knowledge Base.

↓

Use Rules.

↓

Only then call AI.

---

# Failure Handling

If AI is unavailable

Atlas continues functioning.

The user is informed.

AI-dependent tasks pause gracefully.

Tracking.

Memory.

Analytics.

Notifications.

Dashboard.

Browser Companion.

All continue operating.

---

# Model Selection Strategy

The Router selects providers based on task.

Example

Translation

↓

Translation Specialist

↓

Available Provider

↓

Generate

Coding

↓

Coding Specialist

↓

Available Provider

↓

Generate

Research

↓

Research Specialist

↓

Available Provider

↓

Generate

No specialist communicates directly with providers.

Only the Router does.

---

# Structured Deliverables

Atlas does not return conversations.

Atlas returns work products.

Examples

Proposal Package

Translation Package

Research Report

Client Brief

Risk Report

Application Review

Daily Mission

Opportunity Analysis

Project Summary

Learning Report

This makes Atlas operational rather than conversational.

---

# Prompt Construction

Prompts are assembled dynamically.

Components include

System Rules

Constitution

Specialist Instructions

Relevant Memory

Relevant Knowledge

Task Context

Expected Output

Quality Checklist

No prompt is hardcoded.

---

# Confidence Scoring

Every AI response includes

Confidence

High

Medium

Low

Reasons

Evidence Used

Missing Information

Suggested Verification

Atlas never hides uncertainty.

---

# Quality Assurance

Before delivering results

Atlas checks

Completeness

Consistency

Formatting

Hallucination Risk

Missing Requirements

Output Structure

Only then is the result shown.

---

# Learning Loop

Every completed task improves Atlas.

Store

Successful proposals

Rejected proposals

Successful strategies

Failed strategies

Client preferences

Platform behavior

User corrections

AI corrections

Knowledge compounds continuously.

---

# Security

Sensitive information remains local whenever possible.

Only required context is shared with external AI.

Secrets are never included in prompts.

API credentials remain encrypted.

---

# Engineering Principles

The Intelligence Layer must remain

Modular

Replaceable

Observable

Testable

Documented

Independent

Scalable

---

# Acceptance Criteria

The AI Architecture is successful when

Atlas selects the correct specialist.

Atlas minimizes AI usage.

Atlas remembers previous work.

Atlas explains recommendations.

Atlas survives provider failure.

Atlas produces structured deliverables.

Atlas improves over time.

---

# Closing Statement

Artificial Intelligence is not Atlas.

Intelligence is a capability.

Atlas is the operating system that coordinates intelligence.

The value of Atlas comes not from any individual AI model, but from the way it organizes memory, reasoning, knowledge, and execution into one unified professional workflow.