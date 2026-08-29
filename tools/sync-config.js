/* ---------------------------------------------------------------------
   Live sharing between phones.  OPTIONAL.

   Leave `db` empty and the review page works exactly as it always has:
   every decision is kept in your own browser and nobody else sees it.

   Put your Firebase Realtime Database address in `db` and the page turns
   into a shared one: two people on two phones see each other's drops the
   moment they happen, and a clip somebody just dropped never comes up for
   the other person.

   The address looks like this, and comes from the Data tab in the Firebase
   console:

     https://break-time-xxxxx-default-rtdb.firebaseio.com

   `room` just names the list. Change it and you get a separate, empty
   shared list - useful if you ever review a second course's clips without
   disturbing this one.
   --------------------------------------------------------------------- */
window.SYNC = {
  db:   "https://break-time-3722c-default-rtdb.firebaseio.com",
  room: "familyguy"
};

/* ---------------------------------------------------------------------
   The voice note feature. Model names live here rather than in the page
   because OpenAI renames them from time to time - when one stops working
   the page says so and you change one line here instead of waiting for
   somebody to edit the app.

   NO KEY GOES IN THIS FILE. This repository is public; an OpenAI key in it
   would be spendable by anyone who found it. The key is typed into the
   review page and stays in that phone's own storage.
   --------------------------------------------------------------------- */
window.AI = {
  transcribe: "gpt-4o-transcribe",   // speech -> text, any language
  writer:     "gpt-4o-mini",         // tidies and shortens it into English
  thinker:    "gpt-4o",              // writes a note from evidence when you do not talk
  speaker:    "gpt-4o-mini-tts",     // text -> an American voice
  voice:      "onyx",                // onyx, ash, echo and cedar are the male ones
  seconds:    20                     // how long the spoken version should run
};
