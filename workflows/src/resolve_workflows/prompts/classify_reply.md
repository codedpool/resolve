version: 1
You label a written reply that a company sent to a consumer's complaint (an email, a chat message or a letter, in English, Hindi or Hinglish). You receive JSON with `text` and `labels`. Pick the single best label.

- resolved_claimed: the company says the problem is already fixed: the refund was sent, the replacement shipped, the matter is closed. This is only a claim; it has not been checked.
- partial: the company gives or offers less than was asked: part of the money, a voucher instead of cash, some of the items, a promise for only part of the problem.
- rejected: the company refuses: declined, not eligible, outside the policy, no refund will be given.
- needs_info: the company asks the consumer for more before it will act: a photo, a document, a date, a number, a confirmation.
- silence: there is no reply or no content.

When a reply refuses part and offers part, choose partial. When a reply asks for information and also says it is a refusal unless the information comes, choose needs_info. Return JSON with `label` and `confidence` between 0 and 1.
