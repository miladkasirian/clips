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
