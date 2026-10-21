# Protocol

1. Read the ticket above: the objectives it serves, the context pack (the objectives and, for the
   first `lit` tickets, what position's search for the missing prior work found), and the
   Introduction as it stands, so you add to it rather than repeat it.
2. Search: `wayline scout search "<query>"` for each question, and `wayline scout search --citing
   <identifier>` to follow the closest work forward. At most 20 searches in this ticket.
3. Check every work you mean to cite with `wayline scout <identifier>`, and cite it by the slug it
   prints. A work the scout calls no such work is left out; never cite a work you have not scouted.
4. Write `introduction` passages: each claim sentence ends with `{ref:<slug>#abstract}`, and says
   only what the abstract says. Name competing approaches and what remains open.
5. Run `wayline accept` from the worktree root; you write no file, so there is nothing to commit.
6. Return the structured result with `status: done`, the `passages`, every work you drew on in
   `references`, and `proposals` for a work to read in full (`dossier`) or a line of work this
   ticket did not reach (`lit`).
