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
# R's own svg() device (cairo) writes every glyph as an outline: the text checks cannot read it.
ggsave(file.path(out, "ggplot2-cairo-outlines.svg"), box(one), width = 4, height = 3, device = grDevices::svg)
