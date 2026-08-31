"""Phone bridge layer.

The telephone network is NOT free infrastructure, so this is kept separate
from the AI. The AI just consumes/receives audio; the bridge decides WHERE
the two-way audio comes from.

`bridge: none`    -> microphone + speaker (Stage 1, no phone).
`bridge: audio`   -> physical phone -> audio interface -> PC (real-time I/O).
`bridge: twilio`  -> cloud telephony (add API keys + credentials).
`bridge: sip`     -> a SIP softphone/trunk to your own number (harder to run free).
"""
