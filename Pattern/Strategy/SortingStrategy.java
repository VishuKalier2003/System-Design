package Strategy;

import java.util.Arrays;

// Imp- It is generally a singleton instance hence we use @Component
public class SortingStrategy implements Strategy {
    // All the objects or data will pass through one pipe or instance
    @Override public int maxElement(int nums[]) {
        System.out.println("Array sorting technique");
        Arrays.sort(nums);
        return nums[nums.length-1];
    }
}
