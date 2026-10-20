function drift = phaselock_drift(y0)
%PHASELOCK_DRIFT Phase drift of one moth, integrated at a tight tolerance (invented).
opts = odeset('RelTol', 1e-8);
[~, drift] = ode45(@(t, y) -0.1 * y, [0 10], y0, opts);
end
