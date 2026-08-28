"""Fleet detection layer, V1.

Deterministic detectors only. There is no model call anywhere in this
package and there must never be one: a detector that can hallucinate is a
detector whose output cannot be used as evidence.
"""
