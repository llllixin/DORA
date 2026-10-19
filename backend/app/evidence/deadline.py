"""Capture admission and driver waits share a deadline.

A disconnected in-flight COMMIT has an uncertain outcome; timeout is not proof
that PostgreSQL rolled that transaction back.
"""
import time
from sqlalchemy import text
from app.evidence.contracts import EvidenceError


class CaptureDeadline:
    def __init__(self,*,max_elapsed_ms=2000,clock=time.monotonic):
        self.clock=clock;self.end=clock()+max_elapsed_ms/1000
    def remaining(self):return max(0.,self.end-self.clock())
    def remaining_ms(self):return max(0,int(self.remaining()*1000))
    def check(self):
        if self.remaining_ms()<=0:raise EvidenceError('evidence_capture_timeout',503)
    def prepare_session(self,session):
        from app.db_budget import prepare_session
        prepare_session(session,self)
