function R = phaselock_broken(traces)
%PHASELOCK_BROKEN An order parameter left half written (invented): a parenthesis never closes.
ph = angle(hilbert(traces.').';
R = mean(abs(mean(exp(1i * ph), 1)));
end
