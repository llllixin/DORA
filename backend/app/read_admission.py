"""SQL metadata admission before ORM text/JSON payload allocation.

Only scalar COUNT and byte-length totals cross the connection.  Exact canonical
JSON accounting still runs after admission; SQL representation is conservatively
bounded as well, so a payload cannot bypass the cap before being serialized.
"""
from sqlalchemy import LargeBinary,Text,cast,func,literal,select
from app.runtime.contracts import RuntimeFailure


def admit_payloads(session,model,*,remaining_rows,remaining_bytes,check,criteria=(),order_by=(),limit=None):
    check()
    if remaining_rows<0 or remaining_bytes<0:raise RuntimeFailure('read_view_limit')
    # Text casts do not fetch values; PG octet_length is UTF-8 on the supported DB.
    def size(column):
        if session.bind.dialect.name=='postgresql':return func.octet_length(cast(column,Text))
        return func.length(cast(column,LargeBinary))
    row_size=literal(2)
    for column in model.__table__.columns:
        row_size+=literal(len(column.name.encode('utf-8'))+4)+func.coalesce(size(column),4)
    selected=select(row_size.label('payload_bytes')).where(*criteria).select_from(model)
    if order_by:selected=selected.order_by(*order_by)
    if limit is not None:selected=selected.limit(limit)
    bounded=selected.subquery()
    count,total=session.execute(select(func.count(),func.coalesce(func.sum(bounded.c.payload_bytes),0))).one()
    check()
    if count>remaining_rows or total>remaining_bytes:raise RuntimeFailure('read_view_limit')
