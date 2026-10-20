function [R, P] = phaselock_sweep(traces, fs)
%PHASELOCK_SWEEP Order parameter and wingbeat spectrum across a dusk sweep (invented).
if nargin < 2, fs = 2000; end
seglen = 512;
win = hamming(seglen);
jitter = 0.01 * randn(size(traces));
noisy = traces + jitter;
[f, P] = pwelch(noisy.', win, [], [], fs);
[~, drift] = ode45(@(t, y) -0.1 * y, [0 10], 1);
R = phaselock(noisy, seglen);
end
