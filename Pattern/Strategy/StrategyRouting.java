package Strategy;

import java.util.HashMap;
import java.util.Map;


public class StrategyRouting {
    private final Strategy heapStrategy;
    private final Strategy sortingStrategy;

    public final Map<RoutingType, Strategy> strategyMap = new HashMap<>();

    // Imp- Use @Qualifier annotation to direct the beans
    public StrategyRouting(Strategy heapStrategy, Strategy sortingStrategy) {
        this.heapStrategy = heapStrategy;       // Use @Qualifier("component-name-1")
        this.sortingStrategy = sortingStrategy;     // Use @Qualifier("component-name-2")
        // Imp- Map used to store and direct the control to the specific strategy instances
        strategyMap.put(RoutingType.HEAPIFY, this.heapStrategy);
        strategyMap.put(RoutingType.SORTING, this.sortingStrategy);
    }

    public int evaluateStrategy(int nums[], String type) {
        Strategy strategy = strategyMap.get(RoutingType.valueOf(type.toUpperCase()));   // Converting string to enum
        if(strategy == null)
            throw new IllegalArgumentException("Wrong type entered");
        return strategy.maxElement(nums);
    }
}
