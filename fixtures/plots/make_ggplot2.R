# Draw the ggplot2 readability-check samples (ticket 77): Rscript fixtures/plots/make_ggplot2.R fixtures/plots/samples
# Needs ggplot2 and svglite (ggsave writes .svg through svglite); the last sample uses R's own cairo svg() device.
suppressPackageStartupMessages({library(ggplot2); library(svglite)})
args <- commandArgs(trailingOnly = TRUE)
out <- args[1]
dir.create(out, showWarnings = FALSE, recursive = TRUE)
set.seed(7)
LONG <- "mean paired gain over ten seeds at signal 4"
raw <- round(rnorm(12, 0.70, 0.03), 3); x3x4 <- round(rnorm(12, 0.78, 0.03), 3)
long <- rbind(
  data.frame(arm = rep(c("raw", "x3x4"), each = 12), AUROC = c(raw, x3x4), signal = "signal 2"),
  data.frame(arm = rep(c("raw", "x3x4"), each = 12), AUROC = c(raw, x3x4) + 0.02, signal = "signal 4"))
one <- long[long$signal == "signal 2", ]
save <- function(plot, name, width = 4, height = 3) {
  ggsave(file.path(out, paste0(name, ".svg")), plot, width = width, height = height, device = svglite::svglite)
}
box <- function(data) ggplot(data, aes(arm, AUROC)) + geom_boxplot()
heat <- function(rows, cols, missing = 0) {
  cells <- expand.grid(seed = seq_len(cols), signal = seq_len(rows))
  cells$value <- round(runif(nrow(cells)), 2)
  cells <- cells[seq_len(nrow(cells) - missing), ]
  ggplot(cells, aes(factor(seed), factor(signal), fill = value)) + geom_tile() +
    geom_text(aes(label = sprintf("%.2f", value)), size = 2) + labs(x = "seed", y = "signal")
}
save(box(long) + facet_wrap(~signal), "ggplot2-clean", width = 5)
save(heat(6, 6), "ggplot2-heatmap-36")
save(heat(5, 8, missing = 3), "ggplot2-heatmap-37", width = 5)
save(box(one) + theme(axis.text.x = element_text(angle = 45, hjust = 1)), "ggplot2-rotated-ticks")
save(box(one) + labs(x = LONG), "ggplot2-long-label")
save(box(long) + facet_wrap(~signal) + ggtitle("AUROC by arm"), "ggplot2-suptitle", width = 5)
flat <- data.frame(arm = c(rep("raw", 11), rep("x3x4", 12)), AUROC = c(rep(0.7, 9), 0.72, 0.68, x3x4))
save(box(flat), "ggplot2-flat-box")
# Plots the review of ticket 77 found misjudged.
counts <- data.frame(arm = c("raw", "x3x4", "x1x2", "raw", "x3x4", "x1x2"), n = c(1000, 800, 2.5, 600, 700, 0.4),
                     signal = rep(c("signal 2", "signal 4"), each = 3))
save(ggplot(counts, aes(arm, n, fill = signal)) + geom_col() + labs(x = "arm", y = "count",
     caption = "Counts per arm over the ten seeds at both signals") + theme(legend.position = "bottom"),
     "ggplot2-caption-and-bars", width = 5, height = 3.5)
points <- data.frame(x = c(1, 2, 3), y = c(2, 1, 3), label = c("seed 1", "seed 2", "seed 3"))
save(ggplot(points, aes(x, y, label = label)) + geom_point() + geom_text(nudge_y = 0.15) + theme_classic(),
     "ggplot2-points-classic")
tiles <- expand.grid(seed = 1:8, signal = 1:5)
tiles$value <- round(runif(nrow(tiles)), 2)
tiles <- tiles[1:37, ]
save(ggplot(tiles, aes(factor(seed), factor(signal), fill = value)) + geom_tile(width = 0.9, height = 0.9) +
     geom_text(aes(label = sprintf("%.2f", value)), size = 2) + labs(x = "seed", y = "signal"), "ggplot2-tile-gaps-37", width = 5)
# R's own svg() device (cairo) writes every glyph as an outline: the text checks cannot read it.
ggsave(file.path(out, "ggplot2-cairo-outlines.svg"), box(one), width = 4, height = 3, device = grDevices::svg)
