# Intake

## The intent

Prove the M2 path end to end: an experiment ticket's worker writes a job array and returns
`running`; the conductor places the jobs on the GPU one at a time, retries the one that runs out
of GPU memory with a smaller batch, checks and manifests every output, and closes the ticket; the
analysis ticket that waits on it then reads the results and files findings with provenance.

## What exists already

`scripts/train.py`: a logistic regression on a synthetic two-class set, trained for a given
number of seconds, holding `--batch-size` times 8 MiB of GPU memory through the CUDA driver while
it runs, and writing its settings and held-out AUROC as JSON to `--out`.

## References

None.

## Constraints

Standard library only. One GPU on this machine; the owner's reservation keeps cores 0 to 7 and
64 GB.

## Success

Both tickets `done`, three results in `research/manifest.json`, one `job_retried` for the
oversized batch, and a finding whose provenance is a manifested result.
