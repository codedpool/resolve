/** Plain-language text for everything that can go wrong on a voice call. */

const TYPE_INSTEAD = "You can keep going by typing on the case page.";

const MESSAGES = {
  microphone_denied: `The microphone is blocked. Allow microphone access for this site in your browser settings, then choose Start the call again. ${TYPE_INSTEAD}`,
  microphone_missing: `No microphone was found. Plug one in and try again. ${TYPE_INSTEAD}`,
  microphone_unavailable: `The microphone could not be started. Close other apps that may be using it and try again. ${TYPE_INSTEAD}`,
  microphone_unsupported: `This browser cannot record audio for a call. Try a current version of Chrome, Edge, Firefox or Safari. ${TYPE_INSTEAD}`,
  token_expired: "The call link has expired. Choose Start the call to begin again.",
  token_invalid: "The call link has expired. Choose Start the call to begin again.",
  budget_reached: `The voice time for this call has been used up. Everything you confirmed is saved. ${TYPE_INSTEAD}`,
  voice_unavailable: `Voice calls are switched off right now. ${TYPE_INSTEAD}`,
  voice_killed: `Voice calls are switched off right now. ${TYPE_INSTEAD}`,
  session_ended: "This call has already ended. Choose Start the call to begin a new one.",
  connection_lost: "The connection dropped and the call ended. Details you already confirmed are saved. Choose Start the call to try again.",
  connect_failed: "We could not connect the call. Check your internet connection and choose Start the call to try again.",
  not_signed_in: "Sign in again to start a call.",
  rate_limited: "Too many calls were started in a short time. Wait a minute and try again.",
  call_failed: "We could not start the call. Try again in a moment.",
};

const HTTP_CODES = { 401: "not_signed_in", 429: "rate_limited" };

const ENDED = {
  user: "The call has ended.",
  completed: "The call is finished.",
  budget_reached: MESSAGES.budget_reached,
  time_limit: MESSAGES.budget_reached,
  voice_killed: MESSAGES.voice_killed,
  voice_unavailable: MESSAGES.voice_unavailable,
  idle: "The call ended because it was quiet for a long time. Choose Start the call to continue.",
};

export function describeVoiceError(code, fallback) {
  return MESSAGES[code] || fallback || "Something went wrong with the call. Try again in a moment.";
}

/** Maps a failed POST /calls (an ApiError with a status and code) to one of our codes. */
export function codeForRequestError(error) {
  if (error?.code && MESSAGES[error.code]) return error.code;
  if (error?.status && HTTP_CODES[error.status]) return HTTP_CODES[error.status];
  return "call_failed";
}

export function describeEnded(reason) {
  return ENDED[reason] || "The call has ended.";
}
