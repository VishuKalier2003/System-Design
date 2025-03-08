package Strategy;

import Reader.FastReader;

public class TestStrategy {     // Class to test the desired code
    public static void main(String[] args) {
        FastReader fastReader = new FastReader();
        int nums[] = new int[5];
        for(int i = 0; i < nums.length; i++)
            nums[i] = fastReader.nextInt();
        // Creating the strategy object and defining the available strategies
        StrategyRouting strategyRouting = new StrategyRouting(new HeapStrategy(), new SortingStrategy());
        // For now the the strategy selection is at run-time but can be automated by evaluating parameters like port no, active users, etc.
        System.out.println(strategyRouting.evaluateStrategy(nums, "Heapify"));      // strategy selection as Heap
        System.out.println(strategyRouting.evaluateStrategy(nums, "sorting"));      // strategy selection as sorting
    }
}
