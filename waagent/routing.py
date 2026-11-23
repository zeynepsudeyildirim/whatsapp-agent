"""Decides which flow handles an inbound message.

The role of the sender — not anything they write — decides the channel. A customer can never
reach the supplier flow, whatever the message says.
"""

from waagent.db.models import Channel, Role

_ROLE_TO_CHANNEL = {
    Role.ADMIN: Channel.ADMIN,
    Role.SUPPLIER: Channel.SUPPLIER,
    Role.CUSTOMER: Channel.CUSTOMER,
}


def channel_for(role: Role) -> Channel:
    return _ROLE_TO_CHANNEL.get(role, Channel.CUSTOMER)
