package Strategy;

import java.util.Collections;
import java.util.PriorityQueue;

// Imp- It is generally a singleton instance hence we use @Component
public class HeapStrategy implements Strategy {
    // All the objects or data will pass through one pipe or instance
    @Override public int maxElement(int nums[]) {
        System.out.println("Performing Heap operation");
        PriorityQueue<Integer> maxHeap = new PriorityQueue<>(Collections.reverseOrder());
        for(int num : nums)     maxHeap.add(num);
        return maxHeap.peek();
    }
}
