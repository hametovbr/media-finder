## ADDED Requirements

### Requirement: Evidence-based architecture governance
Repository guidance SHALL require an agent proposing or reviewing architecture to state the current goal, verified constraints, compatibility obligations, explicit non-goals, existing ownership, and the least complex sufficient design. It SHALL require a subtraction pass before approval and before merge, and SHALL reject a component, abstraction, compatibility path, automation layer, or process step when no current approved requirement would fail without it.

#### Scenario: Choose an extension boundary
- **WHEN** an agent considers configuration, an adapter, a module, a package, a process, or a service for one change
- **THEN** it selects the lowest level supported by current trust, ownership, release, scaling, isolation, and compatibility evidence and records observable triggers for any higher level it defers

#### Scenario: Review auxiliary machinery
- **WHEN** a helper or verification mechanism duplicates executable behavior or begins interpreting another language's source or control flow
- **THEN** the architecture review evaluates direct execution or a structured existing tool first and rejects the custom interpreter unless an independently approved requirement justifies it

### Requirement: Complexity escalation renews authorization
An approved implementation SHALL stop when its solution crosses into a higher ownership or architecture category than the approved design. Work SHALL resume only after the planning artifacts compare the simpler alternatives, the OpenSpec change is updated, and the revised design receives explicit approval. Examples such as script-to-parser, helper-to-platform, package-to-process, or process-to-service escalation illustrate this general boundary and do not define the purpose of the project guidance.

#### Scenario: Mutation tests expand a validator
- **WHEN** a new bypass would require a bounded validator to tokenize or interpret shell, source-code, or workflow control flow that the approved design did not include
- **THEN** the agent stops apply work and returns to design review instead of adding another parser feature or treating the mutation test as a new product requirement

#### Scenario: Original design remains sufficient
- **WHEN** implementation detail changes without increasing the architecture category, public scope, ownership cost, or compatibility obligation
- **THEN** the agent may continue within the approved apply workflow and records the local decision in normal review evidence
