function drift = phaselock_defaults(y0)
%PHASELOCK_DEFAULTS The drift at the solver's own tolerances, written out by hand (invented).
opts = odeset('RelTol', 0.001, 'AbsTol', 1.0e-6);
[~, drift] = ode45(@(t, y) -0.1 * y, [0 10], y0, opts);
end
