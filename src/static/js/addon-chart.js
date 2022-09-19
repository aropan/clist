/**
 * set fixed width/height option for the legend
 */
Chart.Legend.prototype.afterFit = function() {
    var opts = this.options;
    if (typeof this.options.width === 'number') {
        this.minSize.width = opts.width;
        this.width = opts.width;
    }
    if (typeof this.options.height === 'number') {
        this.minSize.height = opts.height;
        this.height = opts.height;
    }
}

/**
 * Equalize legend width/height for all charts
 * uses maximum width/height
 */
function equalizeLegendWidth(charts) {
    var maxLegendSize = 0;
    charts.forEach(function(chart) {
        var legend = chart.legend;
        var size = legend.isHorizontal()
            ? legend.height
            : legend.width;
        if (size > maxLegendSize) {
            maxLegendSize = size;
        }
    });
    if (maxLegendSize > 0) {
        charts.forEach(function(chart) {
           var legend = chart.legend;

           if (legend.isHorizontal()) {
                chart.legend.options.height = maxLegendSize;
            } else {
                chart.legend.options.width = maxLegendSize;
            }
            chart.update();
        });
    }
}

